"""Sign and publish the address file: where the gateway and the Billing portal are, for every installed app, without a new build.

    python packaging/publish_endpoint.py --init-key
        once: creates the signing key outside the repository and adds its public half to worker/config/endpoint-keys.json
        (the app only trusts keys listed there, so a build made after this step is needed once)
    python packaging/publish_endpoint.py --gateway https://audio-gateway.example.com --billing https://billing.example.com --out <folder> [--push]
        writes endpoint.json and endpoint.json.sig into <folder>, which is a clone of the repository behind one of the places listed in
        worker/config/genius.json `directory` (for example the GitHub Pages repository). With --push it also commits and pushes that clone.
        Publish the same files to every place in `directory` (run once per clone).
    python packaging/publish_endpoint.py --check
        reads the file back from every place in `directory` and says whether each copy is signed and which serial it holds.

The serial is the time of signing, so a newer file always wins and an older copy (a mirror that lags) is ignored by the apps.

Changing domain, in this order: set up the new hostnames on the server (tunnel, API_HOST / BILLING_HOST on the gateway, the payOS webhook and return
URLs), sign and publish the file with the new addresses, run --check, watch the old name stop receiving requests, then drop it.

The signing key: %USERPROFILE%\\.audio-translate\\endpoint-signing.pem (or ENDPOINT_SIGNING_KEY). Keep a copy somewhere safe: without it no new address
can be published until a build ships a new public key. Nothing secret is printed.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / 'worker' / 'config' / 'endpoint-keys.json'
sys.path.insert(0, str(ROOT / 'worker'))


def key_path():
    return Path(os.environ.get('ENDPOINT_SIGNING_KEY') or Path.home() / '.audio-translate' / 'endpoint-signing.pem')


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


def make(gateway, billing, serial=None):
    """(bytes of endpoint.json, signature) for these addresses."""
    from audio_translate.core import endpoint
    serial = serial or int(time.time())
    data = {'schema': endpoint.SCHEMA, 'serial': serial, 'issued_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(serial)), 'gateway': gateway.rstrip('/'), 'billing': billing.rstrip('/')}
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = base64.b64encode(load_key().sign(raw)).decode()
    endpoint.verify(raw, signature, keys=[base64.b64decode(public_b64(load_key()))])   # the app's own checks, before anything is published
    return raw, signature


def write(out, raw, signature):
    out = Path(out)
    if not out.is_dir(): raise SystemExit(f'{out} is not a folder.')
    previous = out / 'endpoint.json'
    if previous.is_file():
        try: old = json.loads(previous.read_text(encoding='utf-8')).get('serial', 0)
        except ValueError: old = 0
        if json.loads(raw)['serial'] <= old: raise SystemExit(f'The serial must be higher than the published one ({old}). Wait a second and try again.')
    (out / 'endpoint.json').write_bytes(raw)
    (out / 'endpoint.json.sig').write_text(signature + '\n', encoding='ascii')


def push(out, gateway):
    run = lambda *args: subprocess.run(['git', '-C', str(out), *args], check=True)
    run('add', 'endpoint.json', 'endpoint.json.sig')
    run('commit', '-m', f'Address file: {gateway}')
    run('push')


def check():
    from audio_translate.core import endpoint
    places = endpoint.mirrors()
    if not places: raise SystemExit('worker/config/genius.json has no `directory` (or none starting with https://).')
    bad = 0
    for base in places:
        try:
            raw, signature = endpoint._get(base + '/endpoint.json'), endpoint._get(base + '/endpoint.json.sig').decode('ascii').strip()
            data = endpoint.verify(raw, signature)
            print(f'OK    {base}  serial {data["serial"]}  gateway {data["gateway"]}  billing {data["billing"]}')
        except Exception as error:
            bad += 1; print(f'FAIL  {base}  {type(error).__name__}: {error}')
    return 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--init-key', action='store_true'); parser.add_argument('--check', action='store_true')
    parser.add_argument('--gateway'); parser.add_argument('--billing'); parser.add_argument('--out'); parser.add_argument('--serial', type=int)
    parser.add_argument('--push', action='store_true')
    args = parser.parse_args(argv)
    if args.init_key: return init_key() or 0
    if args.check: return check()
    if not (args.gateway and args.billing and args.out): parser.error('--gateway, --billing and --out are needed (or --init-key / --check)')
    raw, signature = make(args.gateway, args.billing, args.serial)
    write(args.out, raw, signature)
    print(f'Wrote endpoint.json + endpoint.json.sig (serial {json.loads(raw)["serial"]}) into {args.out}')
    if args.push: push(args.out, args.gateway); print('Committed and pushed. Run --check in a minute or two.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
