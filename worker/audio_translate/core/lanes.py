"""Shared lane ledger: fair parallel units across simultaneous workflows.

Design: docs/MULTI_WORKFLOW_SCHEDULER.md. Each running workflow holds a lease in
`data/config/lanes.json`. Its orchestrator heartbeats the lease; the stage
process (ASR pool, Translation slots, TTS pool) reports units in use and asks
for its target. With a single workflow the target is the stage's own maximum,
so behaviour is unchanged. With several, units are spread one at a time to the
workflow holding the fewest, earlier workflows first, within free RAM minus the
system reserve, physical cores, CPU target and temperature. An earlier
workflow that waits for memory makes later ones shrink to one unit and, if it
still waits, the latest one pauses itself; it resumes automatically later.
"""
import json
import os
import threading
import time
from time import monotonic as _monotonic, sleep as _sleep  # immune to test patches of time.*
from datetime import datetime
from pathlib import Path

from audio_translate.core.storage import DATA, LockedError, atomic_json, file_lock, read_json, update_job

GIB = 1024 ** 3
JOB_ROOTS = ('tmp', 'jobs', 'tool-tmp')


def config_dir(job_dir=None):
    """The data root's config folder; isolated fixtures get their own ledger."""
    if job_dir is None:
        return DATA / 'config'
    path = Path(job_dir).resolve()
    return path.parent.parent / 'config' if path.parent.name in JOB_ROOTS else path.parent / '.lanes'
STALE_SECONDS = 30
HEARTBEAT_SECONDS = 3
YIELD_GRACE_SECONDS = 20
RESUME_COOLDOWN_SECONDS = 60
# Base model and per-unit RAM when a stage has not measured itself yet (dev machine, 16 GB).
DEFAULT_COST = {
    'download': (.3, 0), 'transcription': (.5, 5.2), 'translation': (4.8, .35),  # Hy-MT2-7B Q4_K_M, --no-repack, q8_0 KV
    'moderation': (.2, 0), 'tts': (.3, 1.8),
}


def reserve_bytes():
    return float(os.getenv('LANE_RESERVE_GIB', '2')) * GIB


def stage_cost(stage):
    base, unit = DEFAULT_COST.get(stage, (.3, 0))
    if stage == 'transcription':
        try:
            profile = read_json(DATA / 'config' / 'asr-autotune.json')
            unit = max(unit, profile['peak_bytes'] * 1.25 / GIB)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return int(base * GIB), int(unit * GIB)


def allocate(leases, available, cores, reserve, now=None):
    """Pure allocation. `leases` are dicts sorted or unsorted; returns {id: plan}.

    plan = {target, cores, pause, yielding_for, keep_waiting}
    """
    now = time.time() if now is None else now
    leases = sorted(leases, key=lambda lease: (lease['order'], lease['id']))
    plans = {lease['id']: dict(target=0, cores=cores, pause=False, yielding_for=None, keep_waiting=False)
             for lease in leases}
    if not leases:
        return plans
    if len(leases) == 1:
        lease = leases[0]
        plans[lease['id']].update(target=max(1, lease.get('demand') or 1))
        return plans
    held = sum(lease.get('base_bytes', 0) + lease.get('units', 0) * lease.get('unit_bytes', 0) for lease in leases)
    pool = available + held - reserve
    # The earliest workflow waiting for memory: everyone after it shrinks to one unit.
    waiting = next((lease for lease in leases if lease.get('waiting_bytes')), None)
    used = 0
    pooled = [lease for lease in leases if lease.get('demand', 0) > 0]
    for lease in leases:
        if lease.get('demand', 0) <= 0:
            used += lease.get('base_bytes', 0)
    for index, lease in enumerate(pooled):
        need = lease.get('base_bytes', 0) + lease.get('unit_bytes', 0)
        # The first pooled workflow always keeps its minimum; later ones only if it fits.
        if index == 0 or used + need <= pool or lease.get('units', 0) >= 1:
            plans[lease['id']]['target'] = 1
            used += need
    capped = {lease['id'] for lease in pooled if waiting and lease['order'] > waiting['order']}
    while True:
        total = sum(plans[lease['id']]['target'] for lease in pooled)
        candidates = [lease for lease in pooled
                      if plans[lease['id']]['target'] >= 1 and lease['id'] not in capped
                      and plans[lease['id']]['target'] < lease['demand']
                      and used + lease.get('unit_bytes', 0) <= pool and total < cores]
        if not candidates:
            break
        pick = min(candidates, key=lambda lease: (plans[lease['id']]['target'], lease['order']))
        plans[pick['id']]['target'] += 1
        used += pick.get('unit_bytes', 0)
    total = max(1, sum(plans[lease['id']]['target'] for lease in pooled))
    for lease in pooled:
        target = plans[lease['id']]['target']
        plans[lease['id']]['cores'] = max(1, cores * max(1, target) // total)
    if waiting:
        holders = [lease for lease in leases if lease['order'] > waiting['order']
                   and (lease.get('units', 0) or lease.get('base_bytes', 0) >= GIB // 2)]
        plans[waiting['id']]['keep_waiting'] = bool(holders)
        for lease in holders:
            plans[lease['id']]['yielding_for'] = waiting['id']
        if holders and now - waiting.get('waiting_since', now) >= YIELD_GRACE_SECONDS:
            # Shrinking was not enough: the latest workflow releases its models.
            latest = holders[-1]
            if latest.get('units', 0) <= 1 or now - waiting.get('waiting_since', now) >= 2 * YIELD_GRACE_SECONDS:
                plans[latest['id']]['pause'] = True
    return plans


def snapshot():
    import psutil
    return dict(available=psutil.virtual_memory().available, cores=psutil.cpu_count(logical=False) or 1)


class _Ledger:
    def __init__(self, job_dir=None):
        directory = config_dir(job_dir)
        self.path, self.lock_path = directory / 'lanes.json', directory / 'lanes.lock'

    def __enter__(self):
        deadline = _monotonic() + 5
        while True:
            try:
                self.lock = file_lock(self.lock_path)
                self.lock.__enter__()
                break
            except LockedError:
                if _monotonic() > deadline:
                    raise
                _sleep(.05)
        try:
            self.data = read_json(self.path) if self.path.exists() else {'leases': {}}
        except (OSError, ValueError):
            self.data = {'leases': {}}
        self.original = json.dumps(self.data, sort_keys=True)
        now = time.time()
        self.data['leases'] = {key: value for key, value in self.data.get('leases', {}).items()
                               if now - value.get('heartbeat', 0) <= STALE_SECONDS}
        return self.data

    def __exit__(self, *exc):
        try:
            if exc[0] is None and json.dumps(self.data, sort_keys=True) != self.original:
                atomic_json(self.path, self.data)
        finally:
            self.lock.__exit__(*exc)


def job_id(job_dir):
    return Path(job_dir).name


def _order(job):
    value = job.get('lane_order')
    if value:
        return value
    started = job.get('started_at')
    try:
        return datetime.fromisoformat(started).timestamp() if started else time.time()
    except ValueError:
        return time.time()


def plan_for(job_dir, data=None):
    """Current plan for one workflow (target units, cores, pause...)."""
    if data is None:
        with _Ledger(job_dir) as data:
            pass
    leases = list(data['leases'].values())
    hardware = snapshot()
    plans = allocate(leases, hardware['available'], hardware['cores'], reserve_bytes())
    return plans.get(job_id(job_dir)) or dict(target=10 ** 6, cores=hardware['cores'], pause=False,
                                              yielding_for=None, keep_waiting=False)


def report(job_dir, stage, units, unit_bytes, base_bytes, demand):
    """Stage processes publish usage each observation tick and receive their plan."""
    if not job_dir:
        return dict(target=10 ** 6, cores=os.cpu_count() or 1, pause=False, yielding_for=None, keep_waiting=False)
    try:
        with _Ledger(job_dir) as data:
            lease = data['leases'].get(job_id(job_dir))
            if lease is not None:
                lease.update(stage=stage, units=int(units), unit_bytes=int(unit_bytes or stage_cost(stage)[1]),
                             base_bytes=int(base_bytes if base_bytes is not None else stage_cost(stage)[0]),
                             demand=max(1, int(demand)), reported=time.time())
            plan = plan_for(job_dir, data)
    except (LockedError, OSError):
        return dict(target=10 ** 6, cores=os.cpu_count() or 1, pause=False, yielding_for=None, keep_waiting=False)
    return plan


def waiting(job_dir, need_bytes):
    """Record that this workflow waits for `need_bytes` of RAM (0 clears it).

    Returns True when later workflows still hold memory that will be released,
    so the caller should keep waiting instead of pausing itself.
    """
    if not job_dir:
        return False
    try:
        with _Ledger(job_dir) as data:
            lease = data['leases'].get(job_id(job_dir))
            if lease is None:
                return False
            if need_bytes:
                lease.setdefault('waiting_since', time.time())
                lease['waiting_bytes'] = int(need_bytes)
            else:
                lease.pop('waiting_since', None); lease.pop('waiting_bytes', None)
            return bool(need_bytes) and plan_for(job_dir, data)['keep_waiting']
    except (LockedError, OSError):
        return False


def others_running(job_dir):
    try:
        with _Ledger(job_dir) as data:
            return any(key != job_id(job_dir) for key in data['leases'])
    except (LockedError, OSError):
        return False


def auto_pause(job_dir, for_id=None, reason='lane_yield'):
    """Pause through the normal checkpointed path; the scheduler resumes it later."""
    job_dir = Path(job_dir)
    number = None
    if for_id:
        try:
            number = read_json(job_dir.parent / for_id / 'job.json').get('workflow_no')
        except (OSError, ValueError):
            pass
    text = (f'Tự tạm dừng để ưu tiên workflow #{number:06d}; sẽ tự tiếp tục khi đủ tài nguyên.' if number
            else 'Tự tạm dừng vì thiếu tài nguyên khi chạy nhiều workflow; sẽ tự tiếp tục khi đủ tài nguyên.')
    update_job(job_dir, auto_paused_for=for_id or 'resources', memory_pause_reason=text, auto_paused_at=time.time())
    atomic_json(job_dir / 'working' / 'cancel.signal', {'mode': 'pause', 'reason': reason, 'for': for_id})


class Lease:
    """Held by the orchestrator for the whole run; heartbeats and enforces pause."""

    def __init__(self, job_dir):
        self.job_dir = Path(job_dir)
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        job = read_json(self.job_dir / 'job.json')
        order = _order(job)
        if not job.get('lane_order'):
            update_job(self.job_dir, lane_order=order)
        with _Ledger(self.job_dir) as data:
            data['leases'][job_id(self.job_dir)] = dict(
                id=job_id(self.job_dir), order=order, stage=None, units=0, unit_bytes=0, base_bytes=0,
                demand=0, heartbeat=time.time(), pid=os.getpid(), workflow_no=job.get('workflow_no'))
        self.thread = threading.Thread(target=self._beat, daemon=True)
        self.thread.start()
        return self

    def stage(self, name):
        """A new stage process starts with nothing loaded."""
        self._update(stage=name, units=0, unit_bytes=stage_cost(name)[1] if name else 0, base_bytes=0, demand=0)
        if not name:
            waiting(self.job_dir, 0)

    def _update(self, **fields):
        try:
            with _Ledger(self.job_dir) as data:
                lease = data['leases'].get(job_id(self.job_dir))
                if lease is not None:
                    lease.update(heartbeat=time.time(), **fields)
                return plan_for(self.job_dir, data), dict(data['leases'])
        except (LockedError, OSError):
            return None, {}

    def _beat(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            plan, leases = self._update()
            if plan is None:
                continue
            mine = leases.get(job_id(self.job_dir), {})
            try:
                atomic_json(self.job_dir / 'working' / 'lane.json', dict(
                    workflows=len(leases), target=plan['target'] if len(leases) > 1 else None,
                    units=mine.get('units', 0), stage=mine.get('stage'), cores=plan['cores'],
                    yielding_for=(leases.get(plan['yielding_for']) or {}).get('workflow_no'),
                    waiting=bool(mine.get('waiting_bytes')), updated=time.time()))
                if plan['pause'] and not (self.job_dir / 'working' / 'cancel.signal').exists():
                    auto_pause(self.job_dir, plan['yielding_for'])
            except (OSError, ValueError):
                pass

    def __exit__(self, *exc):
        self.stop.set()
        if self.thread:
            self.thread.join(HEARTBEAT_SECONDS + 1)
        try:
            with _Ledger(self.job_dir) as data:
                data['leases'].pop(job_id(self.job_dir), None)
        except (LockedError, OSError):
            pass  # A stale lease expires after STALE_SECONDS.
        (self.job_dir / 'working' / 'lane.json').unlink(missing_ok=True)


def admission(candidates):
    """Scheduler decision: which queued or auto-paused workflow may start now.

    `candidates` are job dicts (oldest first) with `_dir`, `_next_stage`, `status`.
    Returns (job to start or None, job to resume or None, reasons).
    """
    with _Ledger() as data:
        leases = list(data['leases'].values())
    hardware = snapshot()
    if any(lease.get('waiting_bytes') for lease in leases):
        return None, None, ['A running workflow is waiting for memory']
    held = sum(lease.get('base_bytes', 0) + lease.get('units', 0) * lease.get('unit_bytes', 0) for lease in leases)
    minimum = sum(lease.get('base_bytes', 0) + (lease.get('unit_bytes', 0) if lease.get('demand', 0) else 0)
                  for lease in leases)
    pool = hardware['available'] + held - reserve_bytes()
    running = {lease['id'] for lease in leases}
    now = time.time()
    for job in candidates:
        if job['id'] in running:
            continue
        base, unit = stage_cost(job['_next_stage'])
        if leases and minimum + base + unit > pool:
            continue
        if not leases and job['status'] != 'PAUSED':
            return job, None, []
        if job['status'] == 'PAUSED':
            if now - job.get('auto_paused_at', 0) < RESUME_COOLDOWN_SECONDS:
                continue
            if job.get('auto_paused_for') in running:
                continue  # yielded to that workflow: resuming now would only pause again
            return None, job, []
        # A new workflow only starts when everyone else is already at or near target.
        if hardware['available'] - reserve_bytes() >= base + unit or not leases:
            return job, None, []
    return None, None, []
