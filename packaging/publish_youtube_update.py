"""Publish a yt-dlp release and the YouTube client order to every installed app, without a new build.

    python packaging/publish_youtube_update.py --init-key
        once: creates the signing key outside the repository and adds its public half to worker/config/youtube-update-keys.json
        (the app only trusts keys listed there, so a build made after this step is needed once)
    python packaging/publish_youtube_update.py --bucket audio-translate-models-8386 [--yt-dlp 2026.8.19] [--attempts JSON] [--dry-run]
        downloads the yt-dlp wheel (and the yt-dlp-ejs version it pins) from PyPI, checks PyPI's SHA-256, checks that both import,
        uploads them to youtube/ in the bucket (never replacing an object), then signs and uploads youtube/manifest.json + .sig.
    python packaging/publish_youtube_update.py --ssh ubuntu@HOST --key ~/.ssh/ovh_audio [same options]
        the same onto the gateway server's MODEL_DIR (youtube/ folder) instead of a bucket; the manifest and signature are replaced, wheels never.

The gateway relays the manifest (POST /v1/youtube/update) and signs links to the wheels; it never holds the signing key. Apps check
for a new manifest every check_hours and after a download where every attempt failed.

Roll back: publish again with the older --yt-dlp version (a newer serial is always written, so apps accept it).
Change only the client order: publish again with the same --yt-dlp and a new --attempts.

The signing key: %USERPROFILE%\\.audio-translate\\youtube-update-signing.pem (or YOUTUBE_UPDATE_KEY). Keep a copy somewhere safe:
without it no update can be published until a build ships a new public key. Nothing secret is printed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / 'worker' / 'config' / 'youtube-update-keys.json'
PREFIX = 'youtube/'
sys.path.insert(0, str(ROOT / 'worker'))


def key_path():
    return Path(os.environ.get('YOUTUBE_UPDATE_KEY') or Path.home() / '.audio-translate' / 'youtube-update-signing.pem')


def public_b64(private):
    from cryptography.hazmat.primitives import serialization
    return base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def init_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    path = key_path()
    if path.exists():
        private = load_key()
        print(f'Key already exists: {path}')
    else:
        private = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'xb') as handle:
            handle.write(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        print(f'Created {path}. Back it up: it cannot be recovered.')
    data = json.loads(KEYS.read_text(encoding='utf-8')) if KEYS.exists() else {'keys': []}
    if public_b64(private) not in data['keys']:
        data['keys'].append(public_b64(private))
        KEYS.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        print(f'Public key added to {KEYS.relative_to(ROOT)}. Build the apps once so they trust it.')
    else:
        print('Public key already trusted by the app.')


def load_key():
    from cryptography.hazmat.primitives import serialization
    path = key_path()
    if not path.is_file(): raise SystemExit(f'No signing key at {path}. Run with --init-key first.')
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def gcloud(*args, binary=False):
    tool = shutil.which('gcloud') or shutil.which('gcloud.cmd')
    if not tool: raise SystemExit('gcloud was not found on PATH.')
    return subprocess.run([tool, *args], capture_output=True, text=not binary)


def pypi(name, version=None):
    url = f'https://pypi.org/pypi/{name}/{version}/json' if version else f'https://pypi.org/pypi/{name}/json'
    with urllib.request.urlopen(url, timeout=30) as response: return json.load(response)


def wheel_of(release):
    wheels = [f for f in release['urls'] if f['packagetype'] == 'bdist_wheel' and f['filename'].endswith('-py3-none-any.whl')]
    if len(wheels) != 1: raise SystemExit(f"{release['info']['name']} {release['info']['version']}: no single pure-Python wheel on PyPI.")
    return wheels[0]


def fetch(item, folder):
    path = Path(folder) / item['filename']
    with urllib.request.urlopen(item['url'], timeout=120) as response: path.write_bytes(response.read())
    if hashlib.sha256(path.read_bytes()).hexdigest() != item['digests']['sha256']: raise SystemExit(f"{item['filename']}: SHA-256 differs from PyPI.")
    return path


def smoke(wheels):
    """Both wheels must import together with this Python (the same 3.12 the app ships)."""
    with tempfile.TemporaryDirectory() as folder:
        for path in wheels:
            with zipfile.ZipFile(path) as archive: archive.extractall(folder)
        code = 'import sys; sys.path.insert(0, sys.argv[1]); import yt_dlp, yt_dlp_ejs; from yt_dlp.version import __version__; print(__version__, yt_dlp.__file__.startswith(sys.argv[1]))'
        result = subprocess.run([sys.executable, '-I', '-c', code, folder], capture_output=True, text=True)
        if result.returncode or not result.stdout.strip().endswith('True'): raise SystemExit('The new wheels do not import:\n' + (result.stderr or result.stdout)[-800:])
        return result.stdout.split()[0]


def current_manifest(bucket, store=None):
    if store:
        raw = store.cat(f'{PREFIX}manifest.json')
        try: return json.loads(raw) if raw else None
        except ValueError: return None
    result = gcloud('storage', 'cat', f'gs://{bucket}/{PREFIX}manifest.json')
    if result.returncode: return None
    try: return json.loads(result.stdout)
    except ValueError: return None


def upload_to_server(store, paths, packages, folder, raw, signature):
    """Wheels first (never replaced), checked by size on the server, then the manifest and its signature (replaced)."""
    for path in paths: store.put(path, f'{PREFIX}{path.name}')
    sizes = store.sizes(PREFIX.rstrip('/'))
    for item in packages:
        if sizes.get(item['path']) != item['size']: raise SystemExit(f"{item['path']}: the server holds another size; not publishing the manifest.")
    (Path(folder) / 'manifest.json').write_bytes(raw)
    (Path(folder) / 'manifest.sig').write_text(signature, encoding='ascii')
    for name in ('manifest.json', 'manifest.sig'): store.put(Path(folder) / name, f'{PREFIX}{name}', replace=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--init-key', action='store_true')
    parser.add_argument('--bucket', help='Cloud Storage bucket (the older way)')
    parser.add_argument('--ssh', metavar='USER@HOST', help='publish to the gateway server instead (its MODEL_DIR)')
    parser.add_argument('--key', type=Path, help='private key for --ssh')
    parser.add_argument('--remote-dir', default='/var/lib/audio-gateway/files', help='the gateway MODEL_DIR on the server')
    parser.add_argument('--yt-dlp', dest='version', help='yt-dlp version on PyPI (default: the latest)')
    parser.add_argument('--attempts', help='JSON list of {"client": name or null, "cookies": bool} (default: keep the published order, else the built-in one)')
    parser.add_argument('--check-hours', type=int, default=6)
    parser.add_argument('--dry-run', action='store_true', help='build, check and sign locally; upload nothing')
    args = parser.parse_args()
    if args.init_key: return init_key()
    if bool(args.bucket) == bool(args.ssh): parser.error('give exactly one of --bucket or --ssh')
    if args.ssh:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from remote_files import SshFiles
        store = SshFiles(args.ssh, args.key, args.remote_dir)
    else: store = None
    from audio_translate.transcription import ytdlp_update

    private = load_key()
    trusted = json.loads(KEYS.read_text(encoding='utf-8'))['keys'] if KEYS.exists() else []
    if public_b64(private) not in trusted: raise SystemExit(f'{key_path()} is not in {KEYS.relative_to(ROOT)}; the apps would refuse the manifest.')

    release = pypi('yt-dlp', args.version)
    version = release['info']['version']
    pins = [re.match(r'yt-dlp-ejs\s*==\s*([0-9A-Za-z.+-]+)', r) for r in release['info'].get('requires_dist') or [] if 'yt-dlp-ejs' in r and "extra == 'default'" in r.replace('"', "'")]
    pins = [m[1] for m in pins if m]
    previous = current_manifest(args.bucket, store)
    attempts = json.loads(args.attempts) if args.attempts else (previous or {}).get('attempts') or [dict(s) for s in ytdlp_update.DEFAULT_ATTEMPTS]

    with tempfile.TemporaryDirectory() as folder:
        items = [wheel_of(release)] + ([wheel_of(pypi('yt-dlp-ejs', pins[0]))] if pins else [])
        paths = [fetch(item, folder) for item in items]
        imported = smoke(paths)
        packages = [{'name': 'yt-dlp' if p.name.startswith('yt_dlp-') else 'yt-dlp-ejs', 'version': p.name.split('-')[1], 'path': PREFIX + p.name,
                     'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
        serial = max(int(time.time()), ((previous or {}).get('serial') or 0) + 1)
        manifest = {'schema': 1, 'serial': serial, 'published_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    'packages': packages, 'attempts': attempts, 'check_hours': args.check_hours}
        raw = json.dumps(manifest, indent=1, sort_keys=True).encode('utf-8')
        signature = base64.b64encode(private.sign(raw)).decode()
        ytdlp_update.verify(raw, signature, keys=[base64.b64decode(k) for k in trusted])   # exactly what the app will check
        print(f'yt-dlp {version} (imports as {imported})' + (f' + yt-dlp-ejs {pins[0]}' if pins else '') + f'; serial {serial}; attempts {json.dumps(attempts)}')
        if args.dry_run:
            print('Dry run: nothing uploaded.'); return
        if store:
            upload_to_server(store, paths, packages, folder, raw, signature)
            print('Published. Apps pick it up within check_hours, or at once after a failed download (the gateway caches for 5 minutes).')
            return
        for path in paths:
            result = gcloud('storage', 'cp', '--no-clobber', str(path), f'gs://{args.bucket}/{PREFIX}{path.name}')
            if result.returncode: raise SystemExit(f'Upload of {path.name} failed:\n' + result.stderr[-800:])
        listing = gcloud('storage', 'ls', '-l', f'gs://{args.bucket}/{PREFIX}')
        sizes = {line.split()[-1].rsplit('/', 1)[-1]: int(line.split()[0]) for line in listing.stdout.splitlines() if line.strip().endswith('.whl')}
        for item in packages:
            if sizes.get(Path(item['path']).name) != item['size']: raise SystemExit(f"{item['path']}: the bucket holds another size; not publishing the manifest.")
        (Path(folder) / 'manifest.json').write_bytes(raw)
        (Path(folder) / 'manifest.sig').write_text(signature, encoding='ascii')
        for name in ('manifest.json', 'manifest.sig'):
            result = gcloud('storage', 'cp', '--cache-control=no-store', str(Path(folder) / name), f'gs://{args.bucket}/{PREFIX}{name}')
            if result.returncode: raise SystemExit(f'Upload of {name} failed:\n' + result.stderr[-800:])
    print('Published. Apps pick it up within check_hours, or at once after a failed download (the gateway caches for 5 minutes).')


if __name__ == '__main__':
    main()
