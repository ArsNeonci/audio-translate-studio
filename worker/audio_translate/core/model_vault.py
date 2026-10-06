"""ModelVault interface (Phase 2C) for future private / fine-tuned model weights.

Public upstream weights (FunASR, Hy-MT2, VieNeu, NLLB) are NOT encrypted — only a proprietary
model would be. A sealed model is AES-256-GCM encrypted under the same content key the security
service releases (DPAPI/TPM-protected server side, machine-wrapped in the lease), so a private
model can only be used while the service authorizes it. This is the interface and the reference
sealer/opener; no public model is routed through it today.
"""
import os
from pathlib import Path

MAGIC = b'ATMODEL1\n'
_CHUNK = 1024 * 1024


class ModelVaultError(Exception):
    pass


def _key():
    from audio_translate.core import vault
    try:
        return vault.content_key()
    except vault.VaultError as exc:
        raise ModelVaultError(str(exc))


def seal_model(plaintext_path, sealed_path, key=None):
    """Encrypt a private model file. Build/admin side (key supplied) or online (key from service)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = key or _key()
    data = Path(plaintext_path).read_bytes()
    nonce = os.urandom(12)
    Path(sealed_path).write_bytes(MAGIC + nonce + AESGCM(key).encrypt(nonce, data, b'audio-model-v1'))
    return sealed_path


def open_model(sealed_path, output_path, key=None):
    """Decrypt a sealed private model to `output_path`, obtaining the key from the service."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = Path(sealed_path).read_bytes()
    if not raw.startswith(MAGIC):
        raise ModelVaultError('not a sealed model')
    key = key or _key()
    nonce = raw[len(MAGIC):len(MAGIC) + 12]
    plain = AESGCM(key).decrypt(nonce, raw[len(MAGIC) + 12:], b'audio-model-v1')
    Path(output_path).write_bytes(plain)
    return output_path


def is_sealed(path):
    p = Path(path)
    return p.is_file() and p.read_bytes()[:len(MAGIC)] == MAGIC if p.is_file() else False
