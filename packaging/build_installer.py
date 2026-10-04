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

def source_hash():
    sha=hashlib.sha256()
    files=[]
    for directory in ['app','components','lib','worker','packaging','public']:
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.startswith('test_'))
    files.extend(p for p in (WORKSPACE/'shared-license-sdk'/'license_sdk').glob('*.py'))
    files.extend(p for p in (WORKSPACE/'VieNeu-TTS-main'/'src').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    files.append(WORKSPACE/'VieNeu-TTS-main'/'LICENSE')
    files.append(ROOT/'models'/'Hy-MT2-1.8B-Q8_0'/'provenance.json')
    files.append(ROOT/'runtime'/'llama'/'provenance.json')
    files.append(ROOT/'worker'/'config'/'translation-runtime.json')
    files.append(ROOT/'worker'/'config'/'tts-runtime.json')
    files.extend(p for p in (ROOT/'security-core'/'src').glob('*.rs'))
    files.extend(ROOT/'security-core'/name for name in ['Cargo.toml','Cargo.lock','build.rs','trust-anchor.json'])
    files.extend(ROOT/name for name in ['package.json','package-lock.json','next.config.ts','product.manifest.json','licensing/public-config.json'])
    for path in sorted(files):sha.update(str(path.relative_to(WORKSPACE)).encode());sha.update(path.read_bytes())
    return sha.hexdigest()

def copy_tree(source,target,ignore=None):
    shutil.copytree(source,target,dirs_exist_ok=True,ignore=ignore or shutil.ignore_patterns('__pycache__','*.pyc','.git'))

def python_runtime(target):
    base=Path(sys.base_prefix); target.mkdir(parents=True,exist_ok=True)
    for pattern in ['python*.exe','python*.dll','vcruntime*.dll']:
        for path in base.glob(pattern):shutil.copy2(path,target/path.name)
    copy_tree(base/'DLLs',target/'DLLs')
    copy_tree(base/'Lib',target/'Lib',shutil.ignore_patterns('site-packages','test','tests','__pycache__','*.pyc','idlelib','tkinter','ensurepip'))
    site=target/'Lib'/'site-packages';site.mkdir(parents=True,exist_ok=True)
    # Copy distribution-recorded files only, including packages from user site.
    pending=['cryptography','packaging','yt-dlp[default]','websockets','psutil','funasr','torch','torchaudio','transformers','sentencepiece','soundfile','onnxruntime','sea-g2p','soxr','kaldi-native-fbank','librosa','huggingface-hub','PyYAML','jieba','modelscope','llama-cpp-python']
    visited=set();inventory=[]
    while pending:
        req=Requirement(pending.pop()); name=canonicalize_name(req.name); extras=set(req.extras)
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

def build():
    if os.name!='nt':raise RuntimeError('WINDOWS_REQUIRED')
    config=json.loads((ROOT/'licensing'/'public-config.json').read_text())
    if set(config)!={'product_id','version','scheme'} or config['product_id']!='audio-translate' or config['version'] != json.loads((ROOT/'product.manifest.json').read_text())['version']:raise RuntimeError('PUBLIC_CONFIG_INVALID')
    version=config['version']
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    artifact=dist/f'AudioTranslate-{version}.exe';release=dist/f'release-{version}.json'
    fingerprint=source_hash()
    with file_lock(dist/'build.lock'):
        if release.exists():
            record=json.loads(release.read_text())
            if record['source_sha256']!=fingerprint:raise RuntimeError('VERSION_ALREADY_RELEASED: bump version before changing code')
            if not artifact.exists() or digest(artifact)!=record['installer_sha256']:raise RuntimeError('RELEASE_ARTIFACT_MISSING_OR_MODIFIED')
            print('Existing universal installer verified; no rebuild.');return
        staging=dist/f'staging-{version}';staging.mkdir(exist_ok=True)
        payload=staging/'payload';payload.mkdir(exist_ok=True)
        security_binary=build_security_core()
        env={**os.environ,'AUDIO_NEXT_DIST_DIR':'.next-installer'}
        subprocess.run(['cmd.exe','/c','npm','run','build'],cwd=ROOT,env=env,check=True)
        standalone=ROOT/'.next-installer'/'standalone'
        app_root=standalone/'audio-translates' if (standalone/'audio-translates'/'server.js').exists() else standalone
        copy_tree(app_root,payload/'app',shutil.ignore_patterns('data','.venv','.env*','__pycache__','*.pyc','admin-system','trust-anchor.json'))
        if app_root!=standalone and (standalone/'node_modules').exists():copy_tree(standalone/'node_modules',payload/'app'/'node_modules')
        copy_tree(ROOT/'.next-installer'/'static',payload/'app'/'.next-installer'/'static')
        if (ROOT/'public').is_dir():copy_tree(ROOT/'public',payload/'app'/'public')
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
        shutil.copy2(ROOT/'licensing'/'public-config.json',payload/'app'/'licensing'/'public-config.json')
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
        packages=python_runtime(payload/'runtime'/'python')
        vieneu=WORKSPACE/'VieNeu-TTS-main'
        copy_tree(vieneu/'src',payload/'providers'/'VieNeu'/'src')
        for name in ['LICENSE','LICENSE.md']:
            if (vieneu/name).exists():shutil.copy2(vieneu/name,payload/'providers'/'VieNeu'/name)
        # Ship the exact verified offline model, never a source clone or HF cache.
        model_dir=ROOT/'models'/'Hy-MT2-1.8B-Q8_0'
        model_record=json.loads((model_dir/'provenance.json').read_text())
        from importlib.util import spec_from_file_location, module_from_spec
        spec=spec_from_file_location('translation_download',ROOT/'worker'/'tools'/'download_translation_model.py')
        expected=module_from_spec(spec);spec.loader.exec_module(expected)
        if (model_record['sha256']!=expected.SHA256 or model_record['filename']!=expected.FILENAME
                or (model_dir/expected.FILENAME).stat().st_size!=expected.SIZE
                or digest(model_dir/expected.FILENAME)!=expected.SHA256):
            raise RuntimeError('HY_MT_MODEL_CHECKSUM_MISMATCH')
        destination=payload/'app'/'models'/'Hy-MT2-1.8B-Q8_0'
        destination.mkdir(parents=True,exist_ok=True)
        for name in [expected.FILENAME,'provenance.json','LICENSE','MODEL_CARD.md']:
            shutil.copy2(model_dir/name,destination/name)
        shutil.copy2(ROOT/'packaging'/'launcher.py',payload/'launcher.py')
        shutil.copy2(ROOT/'packaging'/'paths.py',payload/'paths.py')
        (payload/'runtime-inventory.json').write_text(json.dumps(packages,indent=2),encoding='utf-8')
        # Resolve from the shipped server and reject any development-repo fallback.
        resolver = "const p=require('path'),r=require('module').createRequire(process.argv[1]);for(const m of ['next/dist/compiled/next-server/app-route-turbo.runtime.prod.js','next/dist/compiled/next-server/app-page-turbo.runtime.prod.js']){const f=r.resolve(m);if(!f.startsWith(p.join(p.dirname(process.argv[1]),'node_modules')+p.sep))throw Error('EXTERNAL_RUNTIME_DEPENDENCY');}console.log('Standalone Node runtime isolation OK');"
        subprocess.run([str(payload/'runtime'/'node'/'node.exe'),'-e',resolver,str(payload/'app'/'server.js')],check=True)
        # Smoke the shipped runtime without host Python or user-site dependencies.
        subprocess.run([str(payload/'runtime'/'python'/'python.exe'),'-c','import sys, llama_cpp, cryptography, numpy, torch, torchaudio, transformers, funasr, yt_dlp, soundfile, onnxruntime, sea_g2p, soxr, audio_translate.core.storage, audio_translate.workflow.results; assert not any("Roaming" in p or ".venv" in p for p in sys.path); print("Portable runtime imports and isolation OK")'],env={**os.environ,'PYTHONNOUSERSITE':'1'},check=True)
        with zipfile.ZipFile(staging/'payload.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for path in sorted(payload.rglob('*')):
                if path.is_file():archive.write(path,path.relative_to(payload))
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
        if not compiler.is_file():raise RuntimeError('WINDOWS_DOTNET_BUILD_TOOLS_REQUIRED')
        bootstrap=staging/'bootstrap.cs';bootstrap.write_text((ROOT/'packaging'/'installer.cs').read_text().replace('@@VERSION@@',version),encoding='utf-8')
        executable=staging/'bootstrap.exe'
        subprocess.run([str(compiler),'/nologo','/target:winexe','/optimize+','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll','/r:System.Windows.Forms.dll','/out:'+str(executable),str(bootstrap)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        # A bounded stream in the bootstrap exposes this appended archive.
        with artifact.open('wb') as output:
            with executable.open('rb') as source:shutil.copyfileobj(source,output)
            with (staging/'payload.zip').open('rb') as source:shutil.copyfileobj(source,output,1024*1024)
            output.write(b'ATSETUP1'+(staging/'payload.zip').stat().st_size.to_bytes(8,'little'))
        if not artifact.is_file() or artifact.stat().st_size<1000000:raise RuntimeError('INSTALLER_BUILD_FAILED')
        record={'product_id':config['product_id'],'version':config['version'],'source_sha256':fingerprint,'installer_sha256':digest(artifact),'size':artifact.stat().st_size,'payload_files':sum(p.is_file() for p in payload.rglob('*'))}
        release.write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record))
        # The verified installer is the release; staging is not a second product.
        if staging.resolve().parent != dist.resolve():raise RuntimeError('UNSAFE_STAGING_CLEANUP')
        shutil.rmtree(staging)

if __name__=='__main__':build()
