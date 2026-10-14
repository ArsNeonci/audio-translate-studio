"""The Windows "Open" dialog for choosing video clips. A web page cannot learn a file's path, and the merge must read the clips
where they are (they can be many GB), so the local API shows the system dialog itself and returns only the chosen paths.

It is owned by the window in front (the app's, since the person just pressed the button), so it opens over the app.
"""
import ctypes
from ctypes import wintypes
import threading

_busy = threading.Lock()

OFN_ALLOWMULTISELECT, OFN_EXPLORER, OFN_FILEMUSTEXIST, OFN_PATHMUSTEXIST, OFN_NOCHANGEDIR, OFN_HIDEREADONLY = 0x200, 0x80000, 0x1000, 0x800, 0x8, 0x4
BUFFER_CHARS = 65536


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [('lStructSize', wintypes.DWORD), ('hwndOwner', wintypes.HWND), ('hInstance', wintypes.HINSTANCE), ('lpstrFilter', wintypes.LPCWSTR),
                ('lpstrCustomFilter', wintypes.LPWSTR), ('nMaxCustFilter', wintypes.DWORD), ('nFilterIndex', wintypes.DWORD), ('lpstrFile', wintypes.LPWSTR),
                ('nMaxFile', wintypes.DWORD), ('lpstrFileTitle', wintypes.LPWSTR), ('nMaxFileTitle', wintypes.DWORD), ('lpstrInitialDir', wintypes.LPCWSTR),
                ('lpstrTitle', wintypes.LPCWSTR), ('Flags', wintypes.DWORD), ('nFileOffset', wintypes.WORD), ('nFileExtension', wintypes.WORD),
                ('lpstrDefExt', wintypes.LPCWSTR), ('lCustData', wintypes.LPARAM), ('lpfnHook', ctypes.c_void_p), ('lpTemplateName', wintypes.LPCWSTR),
                ('pvReserved', ctypes.c_void_p), ('dwReserved', wintypes.DWORD), ('FlagsEx', wintypes.DWORD)]


def _split(raw):
    """One path, or a folder followed by file names (several files chosen)."""
    parts = raw.split('\x00')
    parts = parts[:parts.index('')] if '' in parts else parts
    if len(parts) <= 1: return parts
    folder = parts[0].rstrip('\\')
    return [f'{folder}\\{name}' for name in parts[1:]]


def _show(title, extensions, result):
    ctypes.windll.ole32.CoInitializeEx(None, 0x2)                    # apartment threaded, as the shell dialog expects
    try:
        pattern = ';'.join(f'*{e}' for e in sorted(extensions))
        filters = f'Video ({pattern})\x00{pattern}\x00*.*\x00*.*\x00\x00'
        buffer = ctypes.create_unicode_buffer(BUFFER_CHARS)
        dialog = OPENFILENAMEW()
        dialog.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        dialog.hwndOwner = ctypes.windll.user32.GetForegroundWindow()
        dialog.lpstrFilter, dialog.nFilterIndex = filters, 1
        dialog.lpstrFile, dialog.nMaxFile = ctypes.cast(buffer, wintypes.LPWSTR), BUFFER_CHARS
        dialog.lpstrTitle = title
        dialog.Flags = OFN_ALLOWMULTISELECT | OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_HIDEREADONLY
        if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
            result['paths'] = _split(ctypes.wstring_at(ctypes.addressof(buffer), BUFFER_CHARS))
        else:
            code = ctypes.windll.comdlg32.CommDlgExtendedError()
            result['paths'] = []
            if code: result['error'] = f'DIALOG_{code:x}'
    finally:
        ctypes.windll.ole32.CoUninitialize()


def choose_videos(title, extensions):
    """The chosen paths in the order Windows lists them ([] when cancelled), or None when a dialog is already open."""
    if not _busy.acquire(blocking=False): return None
    try:
        result = {}
        thread = threading.Thread(target=_show, args=(title, extensions, result), daemon=True)
        thread.start(); thread.join()
        if result.get('error'): raise OSError(result['error'])
        return result.get('paths', [])
    finally:
        _busy.release()
