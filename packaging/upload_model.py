"""Upload the on-device models to where the gateway serves them from (run once per model version): a folder on the gateway server
(--ssh) or the private model bucket (--bucket, the older way).

    python packaging/upload_model.py --bucket audio-translate-models-8386                  the translation model (Hy-MT2-7B)
    python packaging/upload_model.py --bucket audio-translate-models-8386 --asr <folder>   the speech models (files listed in worker/config/asr-models.json)
    python packaging/upload_model.py --ssh ubuntu@HOST --key ~/.ssh/ovh_audio [--asr <folder>]   the same, onto the server's MODEL_DIR (files end up owned by audio-gateway, mode 640)

The file is checked against the size and SHA-256 pinned in worker/tools/download_translation_model.py first, so a damaged local copy
is never uploaded. An object that already exists is never replaced (--no-clobber). After the upload the stored size and CRC32C
are compared with the local file (gcloud always stores CRC32C; its parallel upload stores no MD5). Needs `gcloud` logged in with
write access to the bucket. With --ssh the server's own SHA-256 of each file is compared with the pinned one instead, and a file that is already
there is left alone. Nothing secret is printed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker' / 'tools'))
import download_translation_model as pinned  # noqa: E402

OBJECT = f'models/Hy-MT2-7B-Q4_K_M/{pinned.FILENAME}'  # must equal MODELS in billing-gateway/gateway.py
ASR_PREFIX = 'models/asr/'                              # must equal the prefix the gateway signs for the speech-model bundle


def digest(path, algorithm):
    hasher = hashlib.new(algorithm)
    with path.open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024): hasher.update(chunk)
    return hasher


def gcloud(*args):
    tool = shutil.which('gcloud') or shutil.which('gcloud.cmd')
    if not tool: raise SystemExit('gcloud was not found on PATH.')
    return subprocess.run([tool, *args], capture_output=True, text=True)


def asr_files(source):
    """[(local path, object name, size, sha256)] for every speech-model file, each verified against the manifest first."""
    manifest = json.loads((ROOT / 'worker' / 'config' / 'asr-models.json').read_text(encoding='utf-8'))
    files = []
    for model in manifest['models']:
        base = Path(source) / 'models' / model['dir'] / 'snapshots' / 'master'
        for item in model['files']:
            path = base / item['path']
            if not path.is_file() or path.stat().st_size != item['size'] or digest(path, 'sha256').hexdigest() != item['sha256']:
                raise SystemExit(f"{model['dir']}/{item['path']} does not match the manifest; not uploading.")
            files.append((path, f"{ASR_PREFIX}{model['dir']}/{item['path']}", item['size'], item['sha256']))
    return files


def upload_asr_ssh(store, source):
    files = asr_files(source)
    print(f'{len(files)} files verified locally. Uploading to the server...')
    for path, name, _, _ in files:
        print('  ' + ('uploaded' if store.put(path, name) else 'already there') + f': {name}')
    hashes = store.sha256([name for _, name, _, _ in files])
    wrong = [name for _, name, _, sha in files if hashes.get(name) != sha]
    if wrong: raise SystemExit('The server does not hold these files with the pinned SHA-256: ' + ', '.join(wrong[:5]))
    print(f'OK: {len(files)} files under {ASR_PREFIX} on the server with the pinned SHA-256.')


def upload_model_ssh(store, file):
    if not file.is_file(): raise SystemExit(f'Not found: {file}')
    if file.stat().st_size != pinned.SIZE or digest(file, 'sha256').hexdigest() != pinned.SHA256:
        raise SystemExit('The local model does not match the pinned size/SHA-256; not uploading.')
    print('Local file verified. Uploading to the server (4.6 GB)...')
    print('  ' + ('uploaded' if store.put(file, OBJECT) else 'already there'))
    if store.sha256([OBJECT]).get(OBJECT) != pinned.SHA256: raise SystemExit('The server copy does not match the pinned SHA-256. Do not use it.')
    print(f'OK: {OBJECT} on the server ({pinned.SIZE} bytes, SHA-256 matches).')


def upload_asr(bucket, source):
    """The speech models: every file of the manifest, verified locally against its pinned size and SHA-256, then compared with what the bucket holds."""
    manifest = json.loads((ROOT / 'worker' / 'config' / 'asr-models.json').read_text(encoding='utf-8'))
    groups, expected = {}, {}
    for model in manifest['models']:
        base = Path(source) / 'models' / model['dir'] / 'snapshots' / 'master'
        for item in model['files']:
            path = base / item['path']
            if not path.is_file() or path.stat().st_size != item['size'] or digest(path, 'sha256').hexdigest() != item['sha256']:
                raise SystemExit(f"{model['dir']}/{item['path']} does not match the manifest; not uploading.")
            groups.setdefault(f"{model['dir']}/{Path(item['path']).parent.as_posix()}".rstrip('/.'), []).append(str(path))
            expected[f"gs://{bucket}/{ASR_PREFIX}{model['dir']}/{item['path']}"] = item['size']
    print(f'{len(expected)} files verified locally. Uploading...')
    for prefix, files in sorted(groups.items()):
        result = gcloud('storage', 'cp', '--no-clobber', *files, f'gs://{bucket}/{ASR_PREFIX}{prefix}/')
        if result.returncode: raise SystemExit(f'Upload to {prefix} failed:\n' + result.stderr[-800:])
    listing = gcloud('storage', 'ls', '-l', '-r', f'gs://{bucket}/{ASR_PREFIX}')
    if listing.returncode: raise SystemExit('Could not list the bucket:\n' + listing.stderr[-800:])
    stored = {}
    for line in listing.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and parts[-1].startswith('gs://'): stored[parts[-1]] = int(parts[0])
    wrong = [url for url, size in expected.items() if stored.get(url) != size]
    if wrong: raise SystemExit('The bucket does not hold these files with the right size: ' + ', '.join(wrong[:5]))
    print(f'OK: {len(expected)} files in gs://{bucket}/{ASR_PREFIX} with the pinned sizes.')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bucket', help='Cloud Storage bucket (the older way)')
    parser.add_argument('--ssh', metavar='USER@HOST', help='upload to the gateway server instead (its MODEL_DIR)')
    parser.add_argument('--key', type=Path, help='private key for --ssh')
    parser.add_argument('--remote-dir', default='/var/lib/audio-gateway/files', help='the gateway MODEL_DIR on the server')
    parser.add_argument('--file', type=Path, default=ROOT / 'models' / 'Hy-MT2-7B-Q4_K_M' / pinned.FILENAME)
    parser.add_argument('--asr', type=Path, help='folder that holds models/<org>--<name>/snapshots/master for the speech models')
    args = parser.parse_args()
    if bool(args.bucket) == bool(args.ssh): parser.error('give exactly one of --bucket or --ssh')
    if args.ssh:
        from remote_files import SshFiles
        store = SshFiles(args.ssh, args.key, args.remote_dir)
        return upload_asr_ssh(store, args.asr) if args.asr else upload_model_ssh(store, args.file)
    if args.asr: return upload_asr(args.bucket, args.asr)
    if not args.file.is_file(): raise SystemExit(f'Not found: {args.file}')
    if args.file.stat().st_size != pinned.SIZE or digest(args.file, 'sha256').hexdigest() != pinned.SHA256:
        raise SystemExit('The local model does not match the pinned size/SHA-256; not uploading.')
    target = f'gs://{args.bucket}/{OBJECT}'
    print('Local file verified. Uploading (4.6 GB)...')
    result = gcloud('storage', 'cp', '--no-clobber', str(args.file), target)
    if result.returncode: raise SystemExit('Upload failed:\n' + result.stderr[-800:])
    info = gcloud('storage', 'objects', 'describe', target, '--format=json')
    if info.returncode: raise SystemExit('Could not read the uploaded object:\n' + info.stderr[-800:])
    meta = json.loads(info.stdout)
    local = gcloud('storage', 'hash', str(args.file), '--format=json')
    if local.returncode: raise SystemExit('Could not hash the local file with gcloud:\n' + local.stderr[-800:])
    local_crc = json.loads(local.stdout)[0]['crc32c_hash']
    if int(meta.get('size', 0)) != pinned.SIZE or meta.get('crc32c_hash') != local_crc:
        raise SystemExit('The stored object does not match the local file (size or CRC32C). Do not use it.')
    print(f'OK: {target} ({pinned.SIZE} bytes, CRC32C matches).')


if __name__ == '__main__':
    main()
