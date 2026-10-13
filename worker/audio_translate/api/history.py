"""Saved workflows and tool runs (was lib/server/history.ts), plus the working folder of a job (jobs.ts jobDir)."""
import math
from pathlib import Path
import re
import threading

from audio_translate.api.files import js_number
from audio_translate.api.runtime import worker_command
from audio_translate.core.storage import DATA

JOB_ID = re.compile(r'^[0-9a-f-]{36}$')
_migrated = threading.Lock()
_ready = False


def ensure_history():
    """Migrate the storage once per process (manage.py initialize); a failure is retried on the next call."""
    global _ready
    with _migrated:
        if _ready: return
        result = worker_command('manage.py', {'action': 'initialize'})
        if result.get('status') != 200: raise RuntimeError(result.get('error') or 'Cannot migrate storage')
        _ready = True


def _js_text(value):
    if value is None: return 'undefined'
    if value is True: return 'true'
    if value is False: return 'false'
    return str(value)


def history_list(params, scope='workflows'):
    ensure_history()
    result = worker_command('manage.py', {'action': 'history', 'scope': scope})
    if result.get('status') != 200: raise RuntimeError(result.get('error'))
    jobs = result['jobs']
    statuses = sorted({job['status'] for job in jobs})
    search, status = (params.get('search') or '').lower(), params.get('status')
    filtered = [job for job in jobs if (not status or status == 'ALL' or job['status'] == status)
                and search in ' '.join(_js_text(job.get(k)) for k in ('workflow_no', 'id', 'name', 'url')).lower()]
    filtered.sort(key=lambda job: job['created_at'], reverse=params.get('sort') != 'oldest')
    limit = js_number(params.get('limit'))
    limit = max(1, min(100, limit if limit == limit and limit else 25))
    page = js_number(params.get('page'))
    page = max(1, math.floor(page if page == page and page else 1))
    limit = int(limit) if limit == int(limit) else limit
    start = int((page - 1) * limit)
    return {'jobs': filtered[start:int(start + limit)], 'total': len(filtered), 'page': page, 'limit': limit, 'statuses': statuses}


def history_job(job_id, scope='workflows'):
    if not JOB_ID.match(job_id or ''): return None
    ensure_history()
    result = worker_command('manage.py', {'action': 'history', 'scope': scope})
    return next((job for job in result.get('jobs') or [] if job.get('id') == job_id), None)


def resolve_file(job_id, file_id, scope='workflows'):
    """(item, absolute path) of a saved output, or None."""
    if not JOB_ID.match(job_id or ''): return None
    ensure_history()
    result = worker_command('manage.py', {'action': 'resolve', 'id': job_id, 'file': file_id, 'scope': scope})
    return result.get('resolved') or None


def job_dir(job_id):
    """The working folder of a workflow or tool run (tool-tmp, tmp, or the legacy jobs folder); None for a bad id."""
    if not JOB_ID.match(job_id or ''): return None
    tool = DATA / 'tool-tmp' / job_id
    if (tool / 'job.json').exists(): return tool
    current, legacy = DATA / 'tmp' / job_id, DATA / 'jobs' / job_id
    return legacy if not (current / 'job.json').exists() and (legacy / 'job.json').exists() else current
