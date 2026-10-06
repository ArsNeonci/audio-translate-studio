"""Encrypted asset vault (Phase 2B).

Assets 1-5 (translation prompt/strategy, Hán-Việt names, address profiles, genre/cleanup
lexicons, postprocess data) ship AES-256-GCM encrypted under a content key that the security
service releases only to an authorized caller (integrity + license checked). The plaintext
source is loaded only when no vault file exists, so development keeps working without a vault;
a packaged release ships the `.vault` files and omits the plaintext sources.

Phase 2C: the service will hand back a lease-wrapped content key instead of the embedded one;
this client is unchanged because it only asks the service for the key.
"""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # app root: worker/audio_translate/core/vault.py
VAULT_DIR = ROOT / 'worker' / 'vault'
MAGIC = b'ATVAULT1\n'

_key_cache = None


class VaultError(Exception):
    pass


def content_key():
    """Fetch the vault content key from the service once per process and keep it in memory."""
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    from audio_translate.core.license_gate import native_command, LicenseError
    try:
        result = native_command({'action': 'content_key'})
    except LicenseError as exc:
        raise VaultError(str(exc))
    if result.get('status') != 'OK' or 'content_key' not in result:
        raise VaultError(result.get('status', 'VAULT_UNCONFIGURED'))
    token = result['content_key']
    raw = base64.urlsafe_b64decode(token + '=' * ((-len(token)) % 4))
    if len(raw) != 32:
        raise VaultError('invalid content key')
    _key_cache = raw
    return raw


def vault_path(name):
    return VAULT_DIR / f'{name}.vault'


def available(name):
    return vault_path(name).is_file()


def load_bytes(name):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = vault_path(name).read_bytes()
    if not raw.startswith(MAGIC):
        raise VaultError('damaged vault file')
    nonce = raw[len(MAGIC):len(MAGIC) + 12]
    return AESGCM(content_key()).decrypt(nonce, raw[len(MAGIC) + 12:], name.encode())


def load_json(name, fallback_path=None):
    """Load a vaulted JSON asset, or its plaintext fallback when no vault file is present (dev)."""
    if available(name):
        text = load_bytes(name).decode('utf-8-sig')
    elif fallback_path and Path(fallback_path).is_file():
        text = Path(fallback_path).read_text(encoding='utf-8-sig')
    else:
        raise VaultError(f'no vault or fallback for {name}')
    return json.loads(text)
