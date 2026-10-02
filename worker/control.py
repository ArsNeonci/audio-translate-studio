"""Cooperative cancellation and persisted wall-clock timing."""
from datetime import datetime, timezone
from pathlib import Path
from storage import read_json, update_job
from contextvars import ContextVar
from functools import wraps

_task_depth = ContextVar('workflow_task_depth', default=0)

def stop_mode(job_dir=None):
    if job_dir is None:
        import os
        job_dir = os.getenv('AUDIO_ACTIVE_JOB')
    signal = Path(job_dir)/'working'/'cancel.signal' if job_dir else None
    if not signal or not signal.exists(): return None
    return read_json(signal).get('mode','cancel')

def complete_task(function):
    """A pause drains one durable adapter task; abort remains cancellable."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        check_cancel()
        token = _task_depth.set(_task_depth.get()+1)
        try: return function(*args, **kwargs)
        finally: _task_depth.reset(token)
    return wrapped

class Cancelled(Exception):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def elapsed(start, end=None):
    if not start: return 0
    return max(0, int((datetime.fromisoformat(end or now()) - datetime.fromisoformat(start)).total_seconds()*1000))

def check_cancel(job_dir=None):
    if job_dir is None:
        import os
        job_dir = os.getenv('AUDIO_ACTIVE_JOB')
    if job_dir and (Path(job_dir)/'working'/'cancel.signal').exists():
        if _task_depth.get() and stop_mode(job_dir)=='pause': return
        raise Cancelled('Processing cancelled by user')

def end_run(job_dir, status):
    job = read_json(Path(job_dir)/'job.json')
    end = now()
    update_job(job_dir, status=status, completed_at=end, active_stage=None,
               total_duration_ms=(job.get('total_duration_ms') or 0)+elapsed(job.get('run_started_at'), end), run_started_at=None)

def cancel_run(job_dir, step):
    from errors import transition
    from results import cleanup_temporary, metadata
    paused = stop_mode(job_dir)=='pause'
    transition(job_dir, step, 'PAUSED' if paused else 'CANCELLED')
    cleanup_temporary(job_dir)
    # Incomplete download/VAD is never a completed input or output.
    for pattern in ([] if paused else ['source/*.part*', 'source/*.ytdl']):
        for file in Path(job_dir).glob(pattern):
            if not file.is_symlink(): file.unlink(missing_ok=True)
    if step == 'TRANSCRIPTION' and not (Path(job_dir)/'working'/'vad.done').exists():
        (Path(job_dir)/'working'/'vad.jsonl').unlink(missing_ok=True)
    end_run(job_dir, 'PAUSED' if paused else 'CANCELLED')
    update_job(job_dir, retry_step=None)
    metadata(job_dir)
