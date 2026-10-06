"""Basic / Plus edition, decided by the Product ID compiled into the native core.

Basic never exposes Chinese text: no Chinese artifacts, no `text_zh` in exports,
no Tool 1, no restart from Download / Transcription, and the Chinese working copies
stay encrypted while no worker uses them (`core/sealing.py`).
"""
_cached = None  # One native query per process; tests set this directly.


def tier():
    global _cached
    if _cached is None:
        from audio_translate.core.license_gate import native_command, LicenseError
        try:
            identity = native_command({'action': 'identity'})
            product = identity.get('product_id', '')
            _cached = identity.get('tier') or ('basic' if product.endswith('-basic') else 'plus')
        except LicenseError:
            return 'basic'  # Fail closed (not cached): an unreadable edition hides Chinese.
    return _cached


def is_basic():
    return tier() == 'basic'


def require_chinese_access(action):
    if is_basic(): raise ValueError(f'{action} is not available in the Basic edition')


def strip_chinese(row):
    """Export copy of a translation row without the transcript."""
    return {key: value for key, value in row.items() if key != 'text_zh'}
