"""Encrypt asset data files into worker/vault/*.vault under the content key (Phase 2B).

The content key is the 32 bytes embedded in the release core (trust-anchor.json `content_key`),
held Admin/build side as a hex file. Each asset is AES-256-GCM encrypted with the logical name as
associated data, matching worker/audio_translate/core/vault.py. A hardened release ships the
`.vault` files and omits the plaintext sources; the service releases the key only to an
authorized caller.
"""
import argparse
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent.parent
MAGIC = b'ATVAULT1\n'

# Logical asset name -> source data file relative to the application root. Assets 1-5.
ASSETS = {
    'genre-lexicon': 'worker/config/genre-lexicon.json',      # asset 4: language data
    'source-cleanup': 'worker/config/source-cleanup.json',    # asset 4: language data
    'address-profiles': 'worker/config/address-profiles.json',  # asset 3: forms of address
    'names': 'worker/config/names.json',                      # asset 2: Hán-Việt names
    'translation-prompts': 'worker/config/translation-prompts.json',  # asset 1: prompts/strategy
}


def seal(key, name, data):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, name.encode())


def build(root, key, assets=None):
    """Write vault files for every present asset; return the logical names written."""
    assets = assets or ASSETS
    out = Path(root) / 'worker' / 'vault'
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, rel in assets.items():
        source = Path(root) / rel
        if not source.is_file():
            continue
        (out / f'{name}.vault').write_bytes(seal(key, name, source.read_bytes()))
        written.append(name)
    return written


def load_key(key_file):
    raw = bytes.fromhex(Path(key_file).read_text(encoding='utf-8').strip())
    if len(raw) != 32:
        raise ValueError('content key must be 32 bytes (hex)')
    return raw


def main():
    parser = argparse.ArgumentParser(description='Encrypt asset data into worker/vault/*.vault')
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--key', required=True, help='hex file holding the 32-byte content key')
    args = parser.parse_args()
    written = build(args.root, load_key(args.key))
    print(f'Vault written: {", ".join(written) or "(no asset sources found)"}')


if __name__ == '__main__':
    main()
