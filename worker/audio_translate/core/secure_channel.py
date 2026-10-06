"""Named-pipe client to the security service.

The service (native Rust core running as a Windows service) is the authority for license,
identity and integrity. Python talks to it over a local named pipe with the same 4-byte
length framing the Rust client uses. The pipe name carries the product id so Basic and Plus
installs never share a channel; the id comes from the installed public config, which is only a
rendezvous label, never a trust input.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path

_PIPE_PREFIX = r'\\.\pipe\AudioTranslate.'
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_ERROR_PIPE_BUSY = 231
_MAX = 65536

ROOT = Path(__file__).resolve().parents[3]  # app root: worker/audio_translate/core/secure_channel.py


class ServiceUnavailable(Exception):
    pass


def product_id():
    """Read the product id used to name the pipe, defaulting to the legacy single product."""
    try:
        return json.loads((ROOT / 'licensing' / 'public-config.json').read_text(encoding='utf-8'))['product_id']
    except Exception:
        return 'audio-translate'


def _kernel32():
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    k.WaitNamedPipeW.restype = wintypes.BOOL
    k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.ReadFile.restype = wintypes.BOOL
    k.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.WriteFile.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _open(k, name, timeout_ms):
    invalid = ctypes.c_void_p(-1).value
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        handle = k.CreateFileW(name, _GENERIC_READ | _GENERIC_WRITE, 0, None, _OPEN_EXISTING, 0, None)
        if handle != invalid:
            return handle
        if ctypes.get_last_error() == _ERROR_PIPE_BUSY and time.monotonic() < deadline:
            k.WaitNamedPipeW(name, 2000)
            continue
        raise ServiceUnavailable('security service pipe unavailable')


def _write_all(k, handle, data):
    view = (ctypes.c_char * len(data)).from_buffer_copy(data)
    sent = 0
    while sent < len(data):
        wrote = wintypes.DWORD(0)
        if not k.WriteFile(handle, ctypes.byref(view, sent), len(data) - sent, ctypes.byref(wrote), None) or wrote.value == 0:
            raise ServiceUnavailable('security service write failed')
        sent += wrote.value


def _read_exact(k, handle, n):
    buf = (ctypes.c_char * n)()
    got = 0
    while got < n:
        read = wintypes.DWORD(0)
        if not k.ReadFile(handle, ctypes.byref(buf, got), n - got, ctypes.byref(read), None) or read.value == 0:
            raise ServiceUnavailable('security service read failed')
        got += read.value
    return bytes(buf)


def call(request, product=None, timeout_ms=6000):
    """Send one request to the service and return its JSON response, or raise ServiceUnavailable."""
    body = json.dumps(request).encode('utf-8')
    if len(body) > _MAX:
        raise ServiceUnavailable('request too large')
    name = _PIPE_PREFIX + (product or product_id())
    k = _kernel32()
    handle = _open(k, name, timeout_ms)
    try:
        _write_all(k, handle, len(body).to_bytes(4, 'big') + body)
        length = int.from_bytes(_read_exact(k, handle, 4), 'big')
        if length == 0 or length > 16 * 1024 * 1024:
            raise ServiceUnavailable('invalid response length')
        return json.loads(_read_exact(k, handle, length))
    finally:
        k.CloseHandle(handle)


def available(product=None):
    try:
        call({'action': 'identity'}, product=product, timeout_ms=1500)
        return True
    except Exception:
        return False
