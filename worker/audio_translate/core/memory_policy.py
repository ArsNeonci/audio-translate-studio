"""Available RAM already includes reclaimable Windows standby pages."""
import os
import json
import math
from pathlib import Path

GIB = 1024 ** 3
CONFIG = Path(__file__).resolve().parents[2] / 'config' / 'asr-memory.json'


def settings():
    # Read on every admission/control check so edits apply without a restart.
    value = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    for key in ('start_free_gib', 'extra_worker_gib', 'pressure_reserve_gib'):
        if isinstance(value[key], bool) or not isinstance(value[key], (int, float)) or not math.isfinite(value[key]) or value[key] <= 0:
            raise ValueError(f'{CONFIG}: {key} must be a positive number')
    if type(value['max_workers']) is not int or value['max_workers'] < 0:
        raise ValueError(f'{CONFIG}: max_workers must be a non-negative integer (0 = automatic)')
    return value


def worker_limit(available, loaded_workers=0):
    config = settings()
    budget = available + loaded_workers * int(config['extra_worker_gib'] * GIB)
    first = int(config['start_free_gib'] * GIB)
    step = int(config['extra_worker_gib'] * GIB)
    count = 0 if budget < first else 1 + (budget-first)//step
    return min(config['max_workers'],count) if config['max_workers'] else count


def reserve(total, parallel=False):
    # Existing OS/browser working sets are already deducted from available RAM.
    # User-selected reserve for parallel ASR; model allocation is additional.
    if parallel:
        return int(settings()['pressure_reserve_gib'] * GIB)
    return GIB if total > 32 * GIB else GIB // 2


def commit_available():
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    class Status(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in ('total_phys', 'available_phys',
                'total_commit', 'available_commit', 'total_virtual', 'available_virtual', 'extended')]
    status = Status()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return status.available_commit


def required(total, peak, parallel=False, workers=None, loaded_workers=0):
    config = settings()
    count = workers if workers is not None else (2 if parallel else 1)
    return int((config['start_free_gib'] + (count-1-loaded_workers)*config['extra_worker_gib']) * GIB)


def fits(snapshot, peak, parallel=False, workers=None, loaded_workers=0):
    needed = required(snapshot['total'], peak, parallel, workers, loaded_workers)
    commit = snapshot.get('commit_available')
    return snapshot['available'] >= needed and (commit is None or commit >= int(peak * 1.25) + GIB // 4)
