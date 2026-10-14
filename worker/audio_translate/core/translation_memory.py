"""How much RAM must be free before the translation model starts, as a setting the person moves with a slider (Settings).

The value is the free memory a workflow waits for before it loads the model; with the default it is what one slot needs (the model about 4.8 GiB
plus one slot's context about 0.3 GiB, with a little margin). More free memory is used by the existing formula (each further slot adds
`extra_slot_gib` on top of the reserve), so a higher number does not add slots, it only asks for more room before starting.

The file is read on every check (translation_server.policy() calls it), so a change reaches a workflow that is waiting for memory within seconds,
without restarting anything. The API process writes it, the workers read it, both through the same data folder.
"""
import json
import math
import os
from pathlib import Path

from audio_translate.core.storage import DATA, ROOT, atomic_json

MIN_GIB, MAX_GIB, STEP_GIB, DEFAULT_GIB = 4.0, 8.0, 0.5, 5.5
CONFIG = DATA / 'settings' / 'translation-memory.json'


def _valid(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            and MIN_GIB <= value <= MAX_GIB and abs(value / STEP_GIB - round(value / STEP_GIB)) < 1e-9)


def saved_gib():
    """The value the person chose, or None when nothing (or something unusable) is saved."""
    try:
        value = json.loads(CONFIG.read_text(encoding='utf-8-sig')).get('start_free_gib')
    except (OSError, ValueError, AttributeError):
        return None
    return float(value) if _valid(value) else None


def configured_gib():
    """What the shipped runtime configuration says (the default when the slider was never moved)."""
    path = Path(os.getenv('HY_MT_RUNTIME_CONFIG', ROOT / 'worker' / 'config' / 'translation-runtime.json'))
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig')).get('start_free_gib')
    except (OSError, ValueError, AttributeError):
        return DEFAULT_GIB
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else DEFAULT_GIB


def effective_gib():
    saved = saved_gib()
    return saved if saved is not None else configured_gib()


def save(value):
    """Stores the slider value. Raises ValueError for anything outside 4 to 8 GiB in steps of 0.5."""
    if not _valid(value):
        raise ValueError(f'start_free_gib must be {MIN_GIB:g} to {MAX_GIB:g} GiB in steps of {STEP_GIB:g}')
    atomic_json(CONFIG, {'start_free_gib': float(value)})
    return float(value)


def status():
    import psutil
    memory = psutil.virtual_memory()
    return {'start_free_gib': effective_gib(), 'default_gib': DEFAULT_GIB, 'min_gib': MIN_GIB, 'max_gib': MAX_GIB, 'step_gib': STEP_GIB,
            'customised': saved_gib() is not None,
            'available_gib': round(memory.available / 1024 ** 3, 2), 'total_gib': round(memory.total / 1024 ** 3, 1)}
