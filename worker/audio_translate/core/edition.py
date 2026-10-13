"""Basic / Plus edition, decided by the Product ID compiled into the native core.

Both editions work with the Chinese transcript (workflow, Tool 1, Reprocess, exports).
They differ in voice generation: Basic generates it on the VPS and asks for review first.
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
            return 'basic'  # Fail closed (not cached): an unreadable edition is treated as Basic (remote voice).
    return _cached


def is_basic():
    return tier() == 'basic'
