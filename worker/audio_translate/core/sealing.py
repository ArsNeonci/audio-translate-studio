"""Basic edition: Chinese-bearing working files are encrypted while no worker uses them.

A worker unseals them under the job's `worker.lock`, runs, and seals them again. Each file
is AES-256-GCM encrypted with a per-installation key that Windows DPAPI protects for the
current user, so the copies are unreadable outside this app on this account. This raises
the effort needed to extract the transcript; it is not protection against the machine owner.

Unsealing restores the exact bytes, so done markers and checkpoint digests stay valid.
Unsealing always runs (an upgrade from Basic to Plus reads old jobs); sealing only on Basic.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets

from audio_translate.core.storage import DATA

MAGIC = b'ATSEAL1\n'
SUFFIX = '.sealed'
# Every working file that holds transcript text, Chinese names or Chinese prompts.
PATTERNS = ['transcript.zh.jsonl', 'transcript.zh.md', 'transcript.jsonl', 'transcript.vi.jsonl',
            'transcript.vi.partial.jsonl', 'transcript.vi.moderated.jsonl',
            'working/chunk-*.json', 'working/postprocess.sqlite3', 'working/name-glossary.json',
            'working/characters.json', 'working/genius-state.json']


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    entropy = b'audio-translate-sealing-v1'
    source = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    extra = Blob(len(entropy), ctypes.cast(ctypes.create_string_buffer(entropy, len(entropy)), ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    crypt = ctypes.windll.crypt32
    call = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    # CRYPTPROTECT_UI_FORBIDDEN; current-user scope.
    if not call(ctypes.byref(source), None, ctypes.byref(extra), None, None, 0x1, ctypes.byref(output)):
        raise OSError('Windows secure storage is unavailable')
    try: return ctypes.string_at(output.pbData, output.cbData)
    finally: ctypes.windll.kernel32.LocalFree(output.pbData)


def _key():
    path = DATA/'keys'/'sealing.key'
    if path.exists(): return _dpapi(path.read_bytes(), False)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    temp = path.with_name(path.name + f'.{secrets.token_hex(8)}.tmp')
    temp.write_bytes(_dpapi(key, True))
    try: os.link(temp, path)  # First writer wins; a racing process reads the winner.
    except FileExistsError: pass
    finally: temp.unlink(missing_ok=True)
    return _dpapi(path.read_bytes(), False)


def _write(path, data):
    temp = path.with_name(path.name + f'.{secrets.token_hex(8)}.tmp')
    try:
        with temp.open('wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(temp, path)
    finally: temp.unlink(missing_ok=True)


def sealed(path):
    path = Path(path)
    return path.with_name(path.name + SUFFIX)


def exists(path):
    return Path(path).exists() or sealed(path).exists()


def _plain_files(job_dir):
    for pattern in PATTERNS:
        for path in Path(job_dir).glob(pattern):
            if path.is_file() and not path.is_symlink(): yield path


def seal(job_dir):
    from audio_translate.core.edition import is_basic
    if not is_basic(): return 0
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    job_dir, count, cipher = Path(job_dir), 0, None
    for path in _plain_files(job_dir):
        cipher = cipher or AESGCM(_key())
        nonce = secrets.token_bytes(12)
        label = path.relative_to(job_dir).as_posix().encode()
        _write(sealed(path), MAGIC + nonce + cipher.encrypt(nonce, path.read_bytes(), label))
        path.unlink()
        count += 1
    return count


def unseal(job_dir):
    job_dir, count, cipher = Path(job_dir), 0, None
    for pattern in PATTERNS:
        for box in job_dir.glob(pattern + SUFFIX):
            if not box.is_file() or box.is_symlink(): continue
            plain = box.with_name(box.name[:-len(SUFFIX)])
            if plain.exists():
                # Interrupted seal/unseal: both copies hold the same bytes; plaintext wins.
                box.unlink(); continue
            raw = box.read_bytes()
            if not raw.startswith(MAGIC): raise ValueError('Damaged sealed working file')
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            cipher = cipher or AESGCM(_key())
            nonce = raw[len(MAGIC):len(MAGIC)+12]
            data = cipher.decrypt(nonce, raw[len(MAGIC)+12:], plain.relative_to(job_dir).as_posix().encode())
            _write(plain, data)
            box.unlink()
            count += 1
    return count


@contextmanager
def opened(job_dir):
    """Plaintext inside the block; call while holding the job's worker.lock."""
    unseal(job_dir)
    try: yield
    finally: seal(job_dir)
