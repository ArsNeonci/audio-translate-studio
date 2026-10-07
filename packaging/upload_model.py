"""Upload the offline translation model to the private model bucket that the gateway serves from (run once per model version).

    python packaging/upload_model.py --bucket audio-translate-models-8386

The file is checked against the size and SHA-256 pinned in worker/tools/download_translation_model.py first, so a damaged local copy
is never uploaded. An object that already exists is never replaced (--no-clobber). After the upload the stored size and CRC32C
are compared with the local file (gcloud always stores CRC32C; its parallel upload stores no MD5). Needs `gcloud` logged in with
write access to the bucket. Nothing secret is printed.
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


def digest(path, algorithm):
    hasher = hashlib.new(algorithm)
    with path.open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024): hasher.update(chunk)
    return hasher


def gcloud(*args):
    tool = shutil.which('gcloud') or shutil.which('gcloud.cmd')
    if not tool: raise SystemExit('gcloud was not found on PATH.')
    return subprocess.run([tool, *args], capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--file', type=Path, default=ROOT / 'models' / 'Hy-MT2-7B-Q4_K_M' / pinned.FILENAME)
    args = parser.parse_args()
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
