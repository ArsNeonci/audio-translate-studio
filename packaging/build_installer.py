"""External-repo Windows build. Whitelist payload; no Admin/customer data."""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parent.parent
WORKSPACE=ROOT.parent
sys.path.insert(0,str(WORKSPACE/'shared-license-sdk'))
from license_sdk.windows import file_lock
from build_security_core import build as build_security_core

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def authenticode_sign(path):
    """Phase 3: Authenticode-sign `path` with the release code-signing certificate when provided
    (AUDIO_SIGNING_CERT = .pfx path, AUDIO_SIGNING_PASSWORD, optional AUDIO_SIGNING_TIMESTAMP_URL).
    Needs signtool on PATH. A hardened release requires a cert; dev builds skip signing. The
    certificate is identity-verified and must be obtained by the publisher; it is never in the repo."""
    cert=os.getenv('AUDIO_SIGNING_CERT')
    if not cert:
        if os.getenv('AUDIO_RELEASE_HARDENED')=='1':raise RuntimeError('AUDIO_SIGNING_CERT required for a hardened release build')
        return False
    signtool=shutil.which('signtool') or shutil.which('signtool.exe')
    if not signtool:raise RuntimeError('SIGNTOOL_NOT_FOUND: install the Windows SDK signing tools')
    command=[signtool,'sign','/fd','SHA256','/f',cert]
    if os.getenv('AUDIO_SIGNING_PASSWORD'):command+=['/p',os.environ['AUDIO_SIGNING_PASSWORD']]
    command+=['/tr',os.getenv('AUDIO_SIGNING_TIMESTAMP_URL','http://timestamp.digicert.com'),'/td','SHA256',str(path)]
    subprocess.run(command,check=True)
    return True

# Legacy single product plus the two editions. Admin injects each edition's public
# config and build-only trust anchor into its own files, so builds never overwrite each other.
EDITIONS={'audio-translate':'','audio-translate-basic':'Basic','audio-translate-plus':'Plus'}

def product_files(product):
    if product not in EDITIONS:raise RuntimeError('UNKNOWN_PRODUCT')
    if product=='audio-translate':
        return {'manifest':ROOT/'product.manifest.json','config':ROOT/'licensing'/'public-config.json','anchor':ROOT/'security-core'/'trust-anchor.json'}
    edition=EDITIONS[product].lower()
    return {'manifest':ROOT/'products'/edition/'product.manifest.json','config':ROOT/'licensing'/f'{product}.public-config.json',
            'anchor':ROOT/'security-core'/f'trust-anchor.{product}.json'}

def source_hash(product='audio-translate'):
    sha=hashlib.sha256()
    files=[]
    for directory in ['app','components','lib','worker','packaging','public']:
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.startswith('test_'))
    files.extend(p for p in (WORKSPACE/'shared-license-sdk'/'license_sdk').glob('*.py'))
    files.extend(p for p in (WORKSPACE/'VieNeu-TTS-main'/'src').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files.append(WORKSPACE/'VieNeu-TTS-main'/'LICENSE')
    files.append(ROOT/'models'/'Hy-MT2-7B-Q4_K_M'/'provenance.json')
    files.append(ROOT/'runtime'/'llama'/'provenance.json')
    files.append(ROOT/'worker'/'config'/'translation-runtime.json')
    files.append(ROOT/'worker'/'config'/'tts-runtime.json')
    files.extend(p for p in (ROOT/'security-core'/'src').glob('*.rs'))
    files.extend(ROOT/'security-core'/name for name in ['Cargo.toml','Cargo.lock','build.rs'])
    files.extend(ROOT/name for name in ['package.json','package-lock.json','next.config.ts'])
    files.extend(product_files(product).values())
    for path in sorted(files):sha.update(str(path.relative_to(WORKSPACE)).encode());sha.update(path.read_bytes())
    return sha.hexdigest()

def compile_stub(source_name,output,work,product,version,edition):
    """Compile one of the .NET stubs (installer.cs, uninstaller.cs) with the version and edition filled in."""
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
    if not compiler.is_file():raise RuntimeError('WINDOWS_DOTNET_BUILD_TOOLS_REQUIRED')
    source=(ROOT/'packaging'/source_name).read_text(encoding='utf-8').replace('@@VERSION@@',version).replace('@@PRODUCT@@',product).replace('@@EDITION@@',edition)
    file=Path(work)/(Path(source_name).stem+'-stub.cs');file.write_text(source,encoding='utf-8')
    subprocess.run([str(compiler),'/nologo','/target:winexe','/optimize+','/win32icon:'+str(ROOT/'packaging'/'app-icon.ico'),'/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll','/r:System.Windows.Forms.dll','/out:'+str(output),str(file)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)

def copy_tree(source,target,ignore=None):
    shutil.copytree(source,target,dirs_exist_ok=True,ignore=ignore or shutil.ignore_patterns('__pycache__','*.pyc','.git'))

# Basic generates the voice on the VPS: no VieNeu source and no TTS-only packages in its payload.
# (funasr imports onnxruntime only in its model-export utility, not for transcription.)
TTS_ONLY = {'sea-g2p', 'onnxruntime'}

def python_runtime(target, exclude=frozenset()):
    base=Path(sys.base_prefix); target.mkdir(parents=True,exist_ok=True)
    for pattern in ['python*.exe','python*.dll','vcruntime*.dll']:
        for path in base.glob(pattern):shutil.copy2(path,target/path.name)
    copy_tree(base/'DLLs',target/'DLLs')
    copy_tree(base/'Lib',target/'Lib',shutil.ignore_patterns('site-packages','test','tests','__pycache__','*.pyc','idlelib','tkinter','ensurepip'))
    site=target/'Lib'/'site-packages';site.mkdir(parents=True,exist_ok=True)
    # Copy distribution-recorded files only, including packages from user site.
    pending=[p for p in ['cryptography','packaging','yt-dlp[default]','websockets','psutil','funasr','torch','torchaudio','transformers','sentencepiece','soundfile','onnxruntime','sea-g2p','soxr','kaldi-native-fbank','librosa','huggingface-hub','PyYAML','jieba','modelscope','llama-cpp-python'] if p not in exclude]
    visited=set();inventory=[]
    while pending:
        req=Requirement(pending.pop()); name=canonicalize_name(req.name); extras=set(req.extras)
        if name in exclude:continue
        marker_context=['',*extras]
        if req.marker and not any(req.marker.evaluate({'extra':extra}) for extra in marker_context):continue
        marker=(name,tuple(sorted(extras)))
        if marker in visited:continue
        visited.add(marker);distribution=metadata.distribution(req.name)
        inventory.append({'name':distribution.metadata['Name'],'version':distribution.version})
        for entry in distribution.files or []:
            if '..' in entry.parts or entry.suffix in ['.pyc','.pth'] or '__pycache__' in entry.parts:continue
            source=Path(distribution.locate_file(entry))
            if source.is_file():
                destination=site/str(entry);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
        for dependency in distribution.requires or []:
            child=Requirement(dependency)
            if not child.marker or any(child.marker.evaluate({'extra':extra}) for extra in marker_context):pending.append(str(child))
    (target/'python312._pth').write_text('Lib\nDLLs\nLib/site-packages\n.\n../../app/worker\n',encoding='utf-8')
    return sorted({item['name']:item for item in inventory}.values(),key=lambda d:d['name'].lower())

def build(product='audio-translate', customer=None):
    # customer: optional tag recorded with the release for per-customer traceability (Phase 3).
    if os.name!='nt':raise RuntimeError('WINDOWS_REQUIRED')
    files=product_files(product);edition=EDITIONS[product]
    manifest=json.loads(files['manifest'].read_text(encoding='utf-8'))
    config=json.loads(files['config'].read_text())
    anchor=json.loads(files['anchor'].read_text())
    if (set(config)!={'product_id','version','scheme'} or config['product_id']!=product or manifest['product_id']!=product
            or anchor['product_id']!=product or config['version']!=manifest['version']):raise RuntimeError('PUBLIC_CONFIG_INVALID')
    version=config['version']
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    artifact=(ROOT/manifest['artifact_path']).resolve()
    if artifact.parent!=dist.resolve():raise RuntimeError('ARTIFACT_PATH_INVALID')
    label=f'{product}-{version}' if edition else version
    release=dist/f'release-{label}.json'
    fingerprint=source_hash(product)
    with file_lock(dist/'build.lock'):
        if release.exists():
            record=json.loads(release.read_text())
            if record['source_sha256']!=fingerprint:raise RuntimeError('VERSION_ALREADY_RELEASED: bump version before changing code')
            if not artifact.exists() or digest(artifact)!=record['installer_sha256']:raise RuntimeError('RELEASE_ARTIFACT_MISSING_OR_MODIFIED')
            print('Existing installer verified; no rebuild.');return
        # Short on purpose: modelscope ships files whose staged path is ~260 characters, and Windows stops copying at 259 (LongPathsEnabled is off).
        staging=dist/('s'+hashlib.sha1(label.encode()).hexdigest()[:6]);staging.mkdir(exist_ok=True)
        payload=staging/'payload';payload.mkdir(exist_ok=True)
        # Compile this edition's core into staging; the development binary stays untouched.
        # Release hardening (AUDIO_RELEASE_HARDENED=1) builds the core without the dev_fallback
        # feature, so only the running Windows service can authorize processing. The installer must
        # then register and start that service (see packaging/manage_service.ps1).
        security_binary=build_security_core(files['anchor'],staging/'audio-security-core.exe',ROOT/'security-core'/'target',dev_fallback=os.getenv('AUDIO_RELEASE_HARDENED')!='1')
        # Sign the native authority before it is copied in and hashed by the manifest.
        authenticode_sign(security_binary)
        env={**os.environ,'AUDIO_NEXT_DIST_DIR':'.next-installer'}
        subprocess.run(['cmd.exe','/c','npm','run','build'],cwd=ROOT,env=env,check=True)
        standalone=ROOT/'.next-installer'/'standalone'
        app_root=standalone/'audio-translates' if (standalone/'audio-translates'/'server.js').exists() else standalone
        copy_tree(app_root,payload/'app',shutil.ignore_patterns('data','.venv','.env*','__pycache__','*.pyc','admin-system','trust-anchor*.json','products'))
        if app_root!=standalone and (standalone/'node_modules').exists():copy_tree(standalone/'node_modules',payload/'app'/'node_modules')
        copy_tree(ROOT/'.next-installer'/'static',payload/'app'/'.next-installer'/'static')
        if (ROOT/'public').is_dir():copy_tree(ROOT/'public',payload/'app'/'public')
        basic=edition=='Basic'
        if basic:
            # Refresh the bundled voice list from the build machine's VieNeu presets.
            subprocess.run([sys.executable,str(ROOT/'worker'/'tools'/'export_voice_catalog.py')],check=True)
        if not (ROOT/'worker'/'config'/'voice-catalog.json').is_file():raise RuntimeError('VOICE_CATALOG_MISSING')
        copy_tree(ROOT/'worker',payload/'app'/'worker',shutil.ignore_patterns('tests','dev','docs','test_*','verify_*','smoke_*','tmp*','__pycache__','*.pyc','*.md'))
        runtime_dir = ROOT/'runtime'/'llama'
        runtime_record = json.loads((runtime_dir/'provenance.json').read_text())
        if not (runtime_dir/'llama-server.exe').is_file(): raise RuntimeError('HY_MT_SERVER_RUNTIME_MISSING')
        for name, checksum in runtime_record['files'].items():
            path = (runtime_dir/name).resolve()
            if not path.is_relative_to(runtime_dir.resolve()) or digest(path) != checksum:
                raise RuntimeError('HY_MT_SERVER_RUNTIME_CHECKSUM_MISMATCH')
        copy_tree(runtime_dir,payload/'app'/'runtime'/'llama')
        # The product ships only the compiled authority, never Python service.py.
        native=payload/'app'/'security-core'/'bin';native.mkdir(parents=True,exist_ok=True)
        shutil.copy2(security_binary,native/'audio-security-core.exe')
        (payload/'app'/'licensing').mkdir(exist_ok=True)
        # Only this edition's metadata ships; traced copies of other editions are dropped.
        for path in (payload/'app'/'licensing').iterdir():
            if path.is_file():path.unlink()
        shutil.copy2(files['config'],payload/'app'/'licensing'/'public-config.json')
        # Next tracing must never include local dotenv or processing outputs.
        for path in (payload/'app').rglob('.env*'):path.unlink()
        for forbidden in ['data','.venv','admin-system','shared-license-sdk','license-sdk']:
            unsafe=payload/'app'/forbidden
            if unsafe.exists():
                if not unsafe.resolve().is_relative_to(staging.resolve()):raise RuntimeError('UNSAFE_TRACE_PAYLOAD')
                shutil.rmtree(unsafe)
        node=Path(shutil.which('node.exe'));(payload/'runtime'/'node').mkdir(parents=True,exist_ok=True);shutil.copy2(node,payload/'runtime'/'node'/'node.exe')
        ffmpeg=Path(shutil.which('ffmpeg.exe')).parent
        (payload/'runtime'/'ffmpeg').mkdir(parents=True,exist_ok=True)
        for path in ffmpeg.glob('*'):
            if path.suffix.lower()=='.dll' or path.name in ['ffmpeg.exe','ffprobe.exe']:shutil.copy2(path,payload/'runtime'/'ffmpeg'/path.name)
        packages=python_runtime(payload/'runtime'/'python',TTS_ONLY if basic else frozenset())
        if not basic:
            vieneu=WORKSPACE/'VieNeu-TTS-main'
            copy_tree(vieneu/'src',payload/'providers'/'VieNeu'/'src')
            for name in ['LICENSE','LICENSE.md']:
                if (vieneu/name).exists():shutil.copy2(vieneu/name,payload/'providers'/'VieNeu'/name)
        # Verify the exact offline model that the gateway serves; never ship a source clone or HF cache.
        model_dir=ROOT/'models'/'Hy-MT2-7B-Q4_K_M'
        model_record=json.loads((model_dir/'provenance.json').read_text())
        from importlib.util import spec_from_file_location, module_from_spec
        spec=spec_from_file_location('translation_download',ROOT/'worker'/'tools'/'download_translation_model.py')
        expected=module_from_spec(spec);spec.loader.exec_module(expected)
        if (model_record['sha256']!=expected.SHA256 or model_record['filename']!=expected.FILENAME
                or (model_dir/expected.FILENAME).stat().st_size!=expected.SIZE
                or digest(model_dir/expected.FILENAME)!=expected.SHA256):
            raise RuntimeError('HY_MT_MODEL_CHECKSUM_MISMATCH')
        destination=payload/'app'/'models'/'Hy-MT2-7B-Q4_K_M'
        destination.mkdir(parents=True,exist_ok=True)
        # The weights are checked above but not shipped: the installer must stay under 4 GiB (Windows will not run a larger .exe).
        # The app downloads them after activation from the gateway's signed link and checks the same SHA-256 (lib/server/model-download.ts).
        for name in ['provenance.json','LICENSE','MODEL_CARD.md']:
            shutil.copy2(model_dir/name,destination/name)
        shutil.copy2(ROOT/'packaging'/'launcher.py',payload/'launcher.py')
        shutil.copy2(ROOT/'packaging'/'app-icon.ico',payload/'app.ico')  # the Start-menu shortcut's icon (installer.cs)
        # The uninstaller ships inside the installation (Windows "Installed apps" runs it); it is covered by the signed payload manifest below.
        compile_stub('uninstaller.cs',payload/'uninstall.exe',staging,product,version,edition)
        shutil.copy2(ROOT/'packaging'/'paths.py',payload/'paths.py')
        (payload/'runtime-inventory.json').write_text(json.dumps(packages,indent=2),encoding='utf-8')
        # Resolve from the shipped server and reject any development-repo fallback.
        resolver = "const p=require('path'),r=require('module').createRequire(process.argv[1]);for(const m of ['next/dist/compiled/next-server/app-route-turbo.runtime.prod.js','next/dist/compiled/next-server/app-page-turbo.runtime.prod.js']){const f=r.resolve(m);if(!f.startsWith(p.join(p.dirname(process.argv[1]),'node_modules')+p.sep))throw Error('EXTERNAL_RUNTIME_DEPENDENCY');}console.log('Standalone Node runtime isolation OK');"
        subprocess.run([str(payload/'runtime'/'node'/'node.exe'),'-e',resolver,str(payload/'app'/'server.js')],check=True)
        # Smoke the shipped runtime without host Python or user-site dependencies.
        modules='sys, importlib.util, llama_cpp, cryptography, numpy, torch, torchaudio, transformers, funasr, yt_dlp, soundfile, soxr, audio_translate.core.storage, audio_translate.workflow.results'+('' if basic else ', onnxruntime, sea_g2p')
        absent='; assert importlib.util.find_spec("onnxruntime") is None and importlib.util.find_spec("sea_g2p") is None' if basic else ''
        subprocess.run([str(payload/'runtime'/'python'/'python.exe'),'-c',f'import {modules}{absent}; assert not any("Roaming" in p or ".venv" in p for p in sys.path); print("Portable runtime imports and isolation OK")'],env={**os.environ,'PYTHONNOUSERSITE':'1'},check=True)
        # Phase 2B: encrypt asset data (1-5) into the vault and, for hardened builds, compile the
        # asset code to .pyd. Admin supplies the 32-byte content key (AUDIO_CONTENT_KEY_FILE) whose
        # value must equal the core's embedded content_key (trust anchor). The plaintext asset
        # sources are dropped once the vault carries them.
        content_key_file=os.getenv('AUDIO_CONTENT_KEY_FILE')
        if content_key_file:
            from build_vault import build as build_vault, load_key as load_content_key
            vaulted=build_vault(payload/'app',load_content_key(content_key_file))
            for rel in ['worker/config/genre-lexicon.json','worker/config/source-cleanup.json','worker/config/address-profiles.json','worker/config/names.json','worker/config/translation-prompts.json']:
                (payload/'app'/rel).unlink(missing_ok=True)
            print(f'Vault written: {", ".join(vaulted)}')
            if os.getenv('AUDIO_RELEASE_HARDENED')=='1':
                from build_protected import build as build_protected
                print(f'Compiled asset modules: {", ".join(build_protected(payload/"app"/"worker"))}')
        elif os.getenv('AUDIO_RELEASE_HARDENED')=='1':
            raise RuntimeError('AUDIO_CONTENT_KEY_FILE required for a hardened release build')
        else:
            print('WARNING: AUDIO_CONTENT_KEY_FILE not set; assets ship as plaintext (vault unconfigured).')
        # Sign the payload manifest for install/runtime integrity. Admin supplies the manifest
        # private key out of band (AUDIO_MANIFEST_KEY_FILE, 32-byte hex); its public half must be in
        # the trust anchor (manifest_public_key). Without it the build is unsigned and the shipped
        # core treats integrity as unconfigured — acceptable only for dev, never a signed release.
        manifest_key=os.getenv('AUDIO_MANIFEST_KEY_FILE')
        if manifest_key:
            from build_manifest import load_key, write as write_manifest
            _,entries=write_manifest(payload,version,load_key(manifest_key))
            print(f'Signed payload manifest: {entries} entries')
        elif os.getenv('AUDIO_RELEASE_HARDENED')=='1':
            raise RuntimeError('AUDIO_MANIFEST_KEY_FILE required for a hardened release build')
        else:
            print('WARNING: AUDIO_MANIFEST_KEY_FILE not set; payload manifest unsigned (integrity unconfigured).')
        # Phase 3: final secret scan — never ship a private key, token, DPAPI blob or database.
        from scan_secrets import scan as scan_secrets
        leaks = scan_secrets(payload)
        if leaks:
            raise RuntimeError('SECRET_SCAN_FAILED: ' + '; '.join(f'{reason}:{p.relative_to(payload)}' for p, reason in leaks[:10]))
        print('Secret scan passed.')
        with zipfile.ZipFile(staging/'payload.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for path in sorted(payload.rglob('*')):
                if path.is_file():archive.write(path,path.relative_to(payload))
        executable=staging/'bootstrap.exe'
        compile_stub('installer.cs',executable,staging,product,version,edition)
        # A bounded stream in the bootstrap exposes this appended archive.
        with artifact.open('wb') as output:
            with executable.open('rb') as source:shutil.copyfileobj(source,output)
            with (staging/'payload.zip').open('rb') as source:shutil.copyfileobj(source,output,1024*1024)
            output.write(b'ATSETUP1'+(staging/'payload.zip').stat().st_size.to_bytes(8,'little'))
        if not artifact.is_file() or artifact.stat().st_size<1000000:raise RuntimeError('INSTALLER_BUILD_FAILED')
        # Sign the installer before recording its hash, so the recorded hash is the signed file's.
        authenticode_sign(artifact)
        record={'product_id':config['product_id'],'version':config['version'],'source_sha256':fingerprint,'installer_sha256':digest(artifact),'size':artifact.stat().st_size,'payload_files':sum(p.is_file() for p in payload.rglob('*'))}
        if customer:record['customer']=customer
        release.write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record))
        # The verified installer is the release; staging is not a second product.
        if staging.resolve().parent != dist.resolve():raise RuntimeError('UNSAFE_STAGING_CLEANUP')
        shutil.rmtree(staging)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--product',default='audio-translate',choices=sorted(EDITIONS))
    parser.add_argument('--customer',help='optional per-customer build tag recorded with the release')
    args=parser.parse_args();build(args.product,args.customer)
