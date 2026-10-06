"""Build and sign `payload.manifest.json` for the installed application tree.

The manifest lists every protected file with its SHA-256, type and version, signed by a
dedicated Ed25519 manifest key (never the license root). The private key stays Admin/build
side; the matching public key goes into `security-core/trust-anchor.json` as
`manifest_public_key`, which `build.rs` embeds at compile time. The native core verifies the
whole tree at install and the `runtime`-flagged entries at service start and before each
workflow. Multi-gigabyte public model weights are deliberately excluded.

Signing reuses `license_sdk.crypto` so the canonical wire format matches the Rust verifier.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / 'shared-license-sdk'))
from license_sdk.crypto import private, public, sign  # noqa: E402

DOMAIN = 'payload-manifest-v1'

# Ordered rules: first match wins. (glob, type, runtime-checked).
# `runtime` entries are rehashed at service start and before each workflow; everything is
# hashed at install. Keep this list cheap at runtime: binaries, config and encrypted payloads.
RULES = [
    ('security-core/bin/audio-security-core.exe', 'binary', True),
    ('app/security-core/bin/audio-security-core.exe', 'binary', True),
    ('licensing/public-config.json', 'config', True),
    ('app/licensing/public-config.json', 'config', True),
    ('worker/config/*.json', 'config', True),
    ('app/worker/config/*.json', 'config', True),
    ('worker/vault/*.vault', 'payload', True),
    ('app/worker/vault/*.vault', 'payload', True),
    # Everything else shipped is verified at install only (too large/numerous for runtime).
    ('**/*.py', 'code', False),
    ('**/*.js', 'code', False),
    ('**/*.json', 'code', False),
]

# Never enters the manifest: public model weights, user data, caches, the manifest itself.
EXCLUDE_DIRS = {'models', 'runtime', 'data', 'node_modules', 'providers', '.venv', 'target', '__pycache__'}
EXCLUDE_NAMES = {'payload.manifest.json'}


def classify(relpath):
    """Return (type, runtime) for a relative POSIX path, or None to exclude."""
    from fnmatch import fnmatch
    for pattern, kind, runtime in RULES:
        if fnmatch(relpath, pattern):
            return kind, runtime
    return None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def collect(root, files=None):
    """Classify a set of files (relative POSIX paths) or walk `root` when none is given."""
    root = Path(root)
    if files is None:
        files = []
        for path in root.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root)
            if set(rel.parts) & EXCLUDE_DIRS or rel.name in EXCLUDE_NAMES:
                continue
            files.append(rel.as_posix())
    entries = []
    for rel in sorted(set(files)):
        if rel in EXCLUDE_NAMES:
            continue
        verdict = classify(rel)
        if verdict is None:
            continue
        kind, runtime = verdict
        entries.append({'path': rel, 'sha256': _sha256(root / rel), 'type': kind,
                        'version': 'pending', 'runtime': runtime})
    return entries


def build(root, version, signing_key, files=None):
    """Return a signed manifest dict for `root` at product `version`."""
    entries = collect(root, files)
    for entry in entries:
        entry['version'] = version
    body = {'version': version, 'entries': entries}
    signature = sign(signing_key, DOMAIN, body)
    return {**body, 'signature': signature}


def write(root, version, signing_key, files=None, out=None):
    manifest = build(root, version, signing_key, files)
    out = Path(out or Path(root) / 'payload.manifest.json')
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return out, len(manifest['entries'])


def load_key(key_file):
    """Load a 32-byte manifest private key (hex) from a file Admin keeps outside the repo."""
    raw = bytes.fromhex(Path(key_file).read_text(encoding='utf-8').strip())
    if len(raw) != 32:
        raise ValueError('manifest private key must be 32 bytes (hex)')
    return private(raw)


def main():
    parser = argparse.ArgumentParser(description='Build and sign payload.manifest.json')
    parser.add_argument('--root', required=True, help='installed application tree root')
    parser.add_argument('--version', required=True)
    parser.add_argument('--key', required=True, help='hex file holding the 32-byte manifest private key')
    parser.add_argument('--out')
    parser.add_argument('--print-public', action='store_true', help='also print the public key for trust-anchor.json')
    args = parser.parse_args()
    key = load_key(args.key)
    out, count = write(args.root, args.version, key, out=args.out)
    print(f'Signed manifest: {out} ({count} entries)')
    if args.print_public:
        print(f'manifest_public_key: {public(key)}')


if __name__ == '__main__':
    main()
