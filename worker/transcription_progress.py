"""Independent telemetry; never rewrites job state or model checkpoints."""
from contextlib import contextmanager
from datetime import datetime, timezone
from storage import atomic_json, read_json
from control import Cancelled, stop_mode


def location(job_dir):
    return job_dir / 'working' / 'transcription-progress.json'


def load(job_dir):
    path = location(job_dir)
    return read_json(path) if path.exists() else {'steps': []}


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def phase(job_dir, number, cached=False):
    data = load(job_dir)
    while len(data['steps']) < 4:
        data['steps'].append({'state': 'PENDING', 'progress': 0, 'attempt': 0,
                              'retry_count': 0, 'duration_ms': None})
    item = data['steps'][number - 1]
    if cached:
        item.update(state='COMPLETED', progress=100)
        # Reused checkpoints have no measured runtime in this invocation.
        atomic_json(location(job_dir), data)
        yield
        return
    item.update(state='RUNNING', progress=None, started_at=now(), completed_at=None,
                attempt=item['attempt'] + 1)
    atomic_json(location(job_dir), data)
    try:
        yield
    except BaseException as exc:
        finish(job_dir, number, ('PAUSED' if stop_mode(job_dir)=='pause' else 'CANCELLED') if isinstance(exc, Cancelled) else 'FAILED')
        raise
    else:
        finish(job_dir, number, 'COMPLETED')


def finish(job_dir, number, state):
    data = load(job_dir)
    item = data['steps'][number - 1]
    end = now()
    measured = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(item['started_at'])).total_seconds() * 1000))
    item.update(state=state, completed_at=end,
                duration_ms=(item.get('duration_ms') or 0) + measured)
    if state == 'COMPLETED':
        item['progress'] = 100
    atomic_json(location(job_dir), data)


def report(job_dir, number, done, total):
    if not location(job_dir).exists() or not total:
        return
    data = load(job_dir)
    item = data['steps'][number - 1]
    value = round(min(100, max(0, 100 * done / total)), 1)
    if item['state'] == 'RUNNING' and item.get('progress') != value:
        item['progress'] = value
        atomic_json(location(job_dir), data)
