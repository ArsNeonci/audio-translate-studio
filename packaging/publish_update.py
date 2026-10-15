"""Publish a built release to every installed app: files to the gateway server, then a signed manifest that names them.

    python packaging/publish_update.py --init-key
        once: creates the signing key outside the repository and adds its public half to worker/config/app-update-keys.json
        (the app only trusts keys listed there, so a build made after this step is needed once)
    python packaging/publish_update.py plus --ssh ubuntu@HOST --key <ssh key file> [--channel stable] [--notes-vi "..."] [--notes-en "..."]
                                              [--min-version 3.2.0] [--allow-downgrade] [--app-only] [--dry-run]
        checks the release built by build_edition.py (dist/release-<product>-<version>.json and its two files: the full installer and the
        app-only package), uploads them to updates/<product>/<version>/ on the server (an existing file is never replaced), then signs and uploads
        updates/<product>/<channel>/latest.json + latest.sig. Apps that are online learn of it within a few hours (or when they open) and offer it.

The workflow: build and test a release, run this once for the "test" channel on a spare PC if you want (AUDIO_UPDATE_CHANNEL=test in that app),
then for "stable". Publishing the stable channel marks the release as published: from then on the code of that version number can no longer change
(build_installer.py refuses VERSION_ALREADY_RELEASED), and the next change needs a higher version.

Roll back: publish a manifest with the older version and --allow-downgrade (the serial is always higher, so apps accept it). Make an old release
update: --min-version X (apps older than X show the update as required; it never touches the licence).

The signing key: %USERPROFILE%\\.audio-translate\\app-update-signing.pem (or APP_UPDATE_KEY). Keep a copy somewhere safe: without it no update can be
published until a build ships a new public key. Nothing secret is printed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / 'worker' / 'config' / 'app-update-keys.json'
sys.path.insert(0, str(ROOT / 'worker'))
sys.path.insert(0, str(ROOT / 'packaging'))
EDITIONS = {'basic': 'audio-translate-basic', 'plus': 'audio-translate-plus'}
MAX_INSTALLER = int(3.5 * 1024 ** 3)


def key_path():
    return Path(os.environ.get('APP_UPDATE_KEY') or Path.home() / '.audio-translate' / 'app-update-signing.pem')


def public_b64(private):
    from cryptography.hazmat.primitives import serialization
    return base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def load_key():
    from cryptography.hazmat.primitives import serialization
    path = key_path()
    if not path.is_file(): raise SystemExit(f'No signing key at {path}. Run with --init-key first.')
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def init_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    path = key_path()
    if path.exists():
        private = load_key(); print(f'Key already exists: {path}')
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


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''): sha.update(block)
    return sha.hexdigest()


def release_files(edition):
    """(product, version, record, installer path, app package path) of the release built for `edition`, checked against its record."""
    product = EDITIONS[edition]
    manifest = json.loads((ROOT / 'products' / edition / 'product.manifest.json').read_text(encoding='utf-8'))
    version = manifest['version']
    record_path = ROOT / 'dist' / f'release-{product}-{version}.json'
    if not record_path.is_file(): raise SystemExit(f'{record_path.name} not found: build the release first (python packaging/build_edition.py {edition}).')
    record = json.loads(record_path.read_text(encoding='utf-8'))
    installer = (ROOT / manifest['artifact_path']).resolve()
    package = ROOT / 'dist' / record.get('app_package', '')
    if not installer.is_file() or digest(installer) != record['installer_sha256']: raise SystemExit(f'{installer.name} is missing or differs from the release record.')
    if not package.is_file() or digest(package) != record.get('app_package_sha256'): raise SystemExit(f'{package.name} is missing or differs from the release record.')
    if installer.stat().st_size > MAX_INSTALLER: raise SystemExit('The installer is larger than the 3.5 GiB the app accepts.')
    return product, version, record_path, record, installer, package


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('edition', nargs='?', choices=sorted(EDITIONS))
    parser.add_argument('--init-key', action='store_true')
    parser.add_argument('--ssh', metavar='USER@HOST', help='the gateway server')
    parser.add_argument('--key', type=Path, help='private key for --ssh')
    parser.add_argument('--remote-dir', default='/var/lib/audio-gateway/files', help='the gateway MODEL_DIR on the server')
    parser.add_argument('--channel', default='stable', help='stable (default) or another name, e.g. test (an app reads one channel: AUDIO_UPDATE_CHANNEL)')
    parser.add_argument('--notes-vi', default=''); parser.add_argument('--notes-en', default='')
    parser.add_argument('--min-version', help='apps older than this show the update as required')
    parser.add_argument('--allow-downgrade', action='store_true', help='offer this version even though it is older than an installed one (roll back)')
    parser.add_argument('--app-only', action='store_true', help='publish only the app package; allowed only when the runtime equals the one already published')
    parser.add_argument('--dry-run', action='store_true', help='check, build and sign locally; upload nothing')
    args = parser.parse_args()
    if args.init_key: return init_key()
    if not args.edition or not args.ssh: parser.error('give the edition and --ssh (or --init-key)')
    from remote_files import SshFiles
    from audio_translate.api import app_update

    product, version, record_path, record, installer, package = release_files(args.edition)
    private = load_key()
    trusted = json.loads(KEYS.read_text(encoding='utf-8'))['keys'] if KEYS.exists() else []
    if public_b64(private) not in trusted: raise SystemExit(f'{key_path()} is not in {KEYS.relative_to(ROOT)}; the apps would refuse the manifest.')
    store = SshFiles(args.ssh, args.key, args.remote_dir)
    current = f'updates/{product}/{args.channel}/latest.json'
    raw_previous = store.cat(current)
    try: previous = json.loads(raw_previous) if raw_previous else None
    except ValueError: previous = None
    if args.app_only and not (previous and previous.get('runtime_sha256') == record['runtime_sha256']):
        raise SystemExit('--app-only needs the runtime to be the one already published (the apps that have the old runtime could not take this release).')
    folder = f'updates/{product}/{version}'
    packages = [{'kind': 'app', 'path': f'{folder}/{package.name}', 'size': package.stat().st_size, 'sha256': record['app_package_sha256']}]
    uploads = [(package, packages[0])]
    if not args.app_only:
        packages.append({'kind': 'installer', 'path': f'{folder}/{installer.name}', 'size': installer.stat().st_size, 'sha256': record['installer_sha256']})
        uploads.append((installer, packages[1]))
    serial = max(int(time.time()), ((previous or {}).get('serial') or 0) + 1)
    notes = {k: v for k, v in (('vi', args.notes_vi), ('en', args.notes_en)) if v}
    manifest = {'schema': 1, 'product': product, 'channel': args.channel, 'serial': serial, 'version': version,
                'released_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'notes': notes, 'runtime_sha256': record['runtime_sha256'],
                'min_version': args.min_version, 'allow_downgrade': args.allow_downgrade, 'packages': packages}
    raw = json.dumps(manifest, indent=1, sort_keys=True).encode('utf-8')
    signature = base64.b64encode(private.sign(raw)).decode()
    app_update.verify(raw, signature, keys=[base64.b64decode(k) for k in trusted], product=product, expect_channel=args.channel)   # exactly what the app will check
    print(f'{product} {version} -> channel {args.channel}, serial {serial}: ' + ', '.join(f"{p['kind']} {p['size'] // 1048576} MB" for p in packages))
    if args.dry_run:
        print('Dry run: nothing uploaded.'); return
    for local, item in uploads:
        created = store.put(local, item['path'])
        print(f"  {item['path']}: {'uploaded' if created else 'already on the server'}")
    sizes = store.sizes(folder)
    hashes = store.sha256([item['path'] for _, item in uploads])
    for _, item in uploads:
        if sizes.get(item['path']) != item['size'] or hashes.get(item['path']) != item['sha256']:
            raise SystemExit(f"{item['path']}: the server holds another file; not publishing the manifest.")
    with tempfile.TemporaryDirectory() as work:
        (Path(work) / 'latest.json').write_bytes(raw)
        (Path(work) / 'latest.sig').write_text(signature, encoding='ascii')
        for name in ('latest.json', 'latest.sig'): store.put(Path(work) / name, f'updates/{product}/{args.channel}/{name}', replace=True)
    if args.channel == 'stable':
        record.update(published=True, published_at=manifest['released_at'])
        record_path.write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(f'Marked {record_path.name} as published: this version number can no longer change.')
    print('Published. Apps check within a few hours or when they open (the gateway caches the manifest for a minute).')


if __name__ == '__main__':
    main()
