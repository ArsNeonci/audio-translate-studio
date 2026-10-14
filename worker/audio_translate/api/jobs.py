"""Workflows on disk and the scheduler that starts them (was lib/server/jobs.ts and transcription-progress.ts).

The scheduler is the only owner of running workflow processes: it asks the lane broker (worker/resources.py) which waiting
workflow may start, starts it through the security core, and records a worker that died. Exactly one scheduler may run per
data folder, so all routes that start work moved here together (re-architecture G4).
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid
from urllib.parse import parse_qs, urlsplit

from audio_translate.api.history import ensure_history, job_dir
from audio_translate.api.license import license_denial
from audio_translate.api.runtime import spawn_security_core, worker_command
from audio_translate.core.storage import DATA
from audio_translate.workflow.results import RESULTS

STEPS = ('DOWNLOAD', 'TRANSCRIPTION', 'TRANSLATION', 'MODERATION', 'TTS', 'SUBTITLE', 'VIDEO')
TERMINAL = ('COMPLETED', 'FAILED', 'CANCELLED', 'PAUSED', 'PARTIAL', 'DELETING', 'AWAITING_REVIEW')
# Working-folder files merged into a job when it is read; never written back into job.json.
TELEMETRY = {'asr-runtime.json': 'asr_runtime', 'lane.json': 'lane', 'translation-runtime.json': 'translation_runtime',
             'translation-progress.json': 'translation_progress', 'genius-progress.json': 'genius_progress', 'tts-remote-progress.json': 'tts_remote_progress'}
DERIVED = ('artifacts', 'transcription_steps', *TELEMETRY.values(), 'translation_failures', 'pause_requested', 'delete_requested')


def _iso(moment): return moment.strftime('%Y-%m-%dT%H:%M:%S.') + f'{moment.microsecond // 1000:03d}Z'


def now_iso():
    """JavaScript's new Date().toISOString(): UTC, milliseconds, Z."""
    return _iso(datetime.now(timezone.utc))


def iso_from_timestamp(seconds): return _iso(datetime.fromtimestamp(seconds, timezone.utc))


def parse_ms(value):
    """Date.parse of the ISO strings the worker and this module write; None when unreadable."""
    if not isinstance(value, str) or not value: return None
    try: return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError: return None


def valid_youtube_url(value):
    try: url = urlsplit(value)
    except ValueError: return False
    host = (url.hostname or '').lower()
    try: port = url.port
    except ValueError: return False
    if url.scheme != 'https' or url.username or url.password or port: return False
    if host in ('youtu.be', 'www.youtu.be'): return bool(re.fullmatch(r'/[\w-]{11}/?', url.path, re.ASCII))
    if host not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'): return False
    if url.path == '/watch': return bool(re.fullmatch(r'[\w-]{11}', (parse_qs(url.query).get('v') or [''])[0], re.ASCII))
    return bool(re.fullmatch(r'/(shorts|live)/[\w-]{11}/?', url.path, re.ASCII))


def transcription_view(job, checkpoints=None):
    """The four Transcription phases for a job that has no recorded telemetry (transcription-progress.ts)."""
    checkpoints = checkpoints or {}
    if len(job.get('transcription_steps') or []) == 4: return job['transcription_steps']
    parent = (job.get('steps') or {}).get('TRANSCRIPTION')
    completed = (parent or {}).get('state') == 'COMPLETED'
    status = job.get('status')
    current = 5 if completed else 4 if status in ('MERGING', 'TRANSCRIPTION_COMPLETED') else 1 if status == 'VAD' \
        else 3 if checkpoints.get('chunks') or job.get('chunks_total') else 2 if checkpoints.get('vad') else 1
    active = (parent or {}).get('state') == 'RUNNING'
    reliable = (parent or {}).get('attempt') == 1
    starts = [(parent or {}).get('started_at'), checkpoints.get('vad'), checkpoints.get('chunks'), None] if reliable else []
    stopped = (parent or {}).get('completed_at') if current == 3 and (parent or {}).get('state') in ('CANCELLED', 'PAUSED', 'FAILED') else None
    ends = [checkpoints.get('vad'), checkpoints.get('chunks'), stopped, None] if reliable else []
    view = []
    for number in (1, 2, 3, 4):
        state = 'COMPLETED' if completed or number < current else parent['state'] if number == current and parent and parent.get('state') != 'PENDING' else 'PENDING'
        if state == 'COMPLETED': progress = 100
        elif state == 'PENDING': progress = 0
        elif number == 3 and job.get('chunks_total'): progress = 100 * (job.get('chunks_done') or 0) / job['chunks_total']
        elif number == 1 and status == 'VAD' and job.get('duration_ms'): progress = 100 * (job.get('processed_ms') or 0) / job['duration_ms']
        else: progress = None
        start = starts[number - 1] if starts else None
        end = ends[number - 1] if ends else None
        item = {'state': state, 'progress': progress, 'retry_count': 0, 'attempt': 0, 'inferred': True}
        if state == 'RUNNING' and active and start: item['started_at'] = start
        a, b = parse_ms(start), parse_ms(end)
        item['duration_ms'] = max(0, b - a) if start and end and a is not None and b is not None else None
        view.append(item)
    return view


def _read_json(path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return default


def get_job(job_id):
    folder = job_dir(job_id)
    if not folder: return None
    job = _read_json(folder / 'job.json')
    if not isinstance(job, dict): return None
    try:
        saved = RESULTS / (job.get('storage_scope') or 'workflows') / str(job['workflow_no']).zfill(6) if job.get('workflow_no') else RESULTS / job_id
        files = (_read_json(saved / 'outputs.json', {'files': []}) or {}).get('files') or []
        available = lambda kind: any(f.get('type') == kind and f.get('status') == 'AVAILABLE' for f in files)
        for step, state in (job.get('steps') or {}).items(): state['output_manifest'] = [{'status': f.get('status')} for f in files if f.get('step') == step]
        job['artifacts'] = {'source': available('SOURCE_AUDIO'), 'zh': available('ZH_MD'), 'vi': available('VI_MD'),
                            'moderated': available('MODERATED_MD'), 'voice': available('VOICE_WAV'), 'subtitle': available('SUBTITLE_SRT'), 'video': available('VIDEO_MP4')}
        working = folder / 'working'
        job['delete_requested'] = (working / 'delete-request.json').exists()
        stop = _read_json(working / 'cancel.signal')
        job['pause_requested'] = bool(stop) and stop.get('mode') == 'pause' and job.get('status') != 'PAUSED'
        # An unreadable telemetry file is skipped (jobs.ts dropped the whole job from the list instead).
        telemetry = _read_json(working / 'transcription-progress.json')
        if isinstance(telemetry, dict): job['transcription_steps'] = telemetry.get('steps')
        for name, key in TELEMETRY.items():
            value = _read_json(working / name)
            if value is not None: job[key] = value
        errors = _read_json(working / 'translation-errors.json')
        if isinstance(errors, dict): job['translation_failures'] = errors.get('failures')
        if not job.get('transcription_steps'):
            stamp = lambda name: iso_from_timestamp((working / name).stat().st_mtime) if (working / name).exists() else None
            job['transcription_steps'] = transcription_view(job, {'vad': stamp('vad.done'), 'chunks': stamp('chunks.json')})
        return job
    except Exception: return None


def list_jobs(include_tools=False):
    ensure_history()
    (DATA / 'tmp').mkdir(parents=True, exist_ok=True)
    folders = [DATA / 'tmp', DATA / 'jobs'] + ([DATA / 'tool-tmp'] if include_tools else [])
    ids = {entry.name for folder in folders if folder.is_dir() for entry in folder.iterdir() if entry.is_dir()}
    jobs = [job for job in (get_job(i) for i in ids) if job and (include_tools or job.get('storage_scope') != 'tools')]
    return sorted(jobs, key=lambda job: job.get('created_at') or '', reverse=True)


def save(job):
    folder = job_dir(job['id'])
    persisted = {k: v for k, v in job.items() if k not in DERIVED}
    temp = folder / f'job.{uuid.uuid4()}.json.tmp'
    temp.write_text(json.dumps(persisted, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, folder / 'job.json')


def retry_job(job_id):
    job = get_job(job_id)
    if not job or not (job.get('status') == 'FAILED' or (job.get('status') == 'COMPLETED' and job.get('workflow_version') != 2 and (job.get('artifacts') or {}).get('zh'))):
        return None
    if job.get('status') == 'FAILED' and job.get('steps'):
        step = next((key for key, state in job['steps'].items() if state.get('state') == 'FAILED'), None)
        if not step: return None
        if worker_command('retry.py', {'action': 'retry', 'id': job_id, 'step': step, 'fresh': True}).get('status') != 202: return None
        scheduler.soon()
        return get_job(job_id)
    following = {**job, 'status': 'QUEUED', 'error': None}
    save(following)
    scheduler.soon()
    return following


def worker_failure(job, code, message):
    step = job.get('retry_step') or (job.get('active_stage') or '').upper() or (job.get('tool_steps') or [None])[0] or 'DOWNLOAD'
    steps = job.get('steps') or {key: {'state': 'PENDING', 'attempt': 0, 'retry_count': 0} for key in STEPS}
    item = steps[step]
    failed_at = now_iso()
    error = {'step': step, 'error_code': code, 'error_message': message, 'error_type': 'WorkerProcessError', 'recoverable_manually': code == 'PATH_MISSING',
             'failed_at': failed_at, 'retry_count': item.get('retry_count')}
    started = parse_ms(item.get('started_at'))
    item.update(state='FAILED', error=error, completed_at=failed_at, duration_ms=max(0, parse_ms(failed_at) - started) if started is not None else 0)
    run_start = parse_ms(job.get('run_started_at'))
    total = (job.get('total_duration_ms') or 0) + (max(0, parse_ms(failed_at) - run_start) if run_start is not None else 0)
    save({**job, 'steps': steps, 'status': 'FAILED', 'completed_at': failed_at, 'run_started_at': None, 'total_duration_ms': total, 'active_stage': None,
          'retry_step': None, 'failed_stage': step.lower(), 'error': message})
    with open(job_dir(job['id']) / 'errors.jsonl', 'a', encoding='utf-8') as log:
        log.write(json.dumps({**error, 'attempt': item.get('attempt') or 1, 'timestamp': failed_at, 'message': message}, ensure_ascii=False) + '\n')


class Scheduler:
    def __init__(self):
        self.active = {}                 # job id -> Popen of its workflow process
        self.running = threading.Lock()  # one scheduling pass at a time; a pass already running makes a call return
        self.retry_timer = None

    def active_count(self): return len(self.active)

    def soon(self, delay=0.0):
        """Run a pass in the background (`void schedule()`), now or after `delay` seconds."""
        timer = threading.Timer(delay, self.schedule); timer.daemon = True; timer.start()

    def _retry_later(self):
        """Re-evaluate admission while workflows wait, even when no page is polling."""
        if self.retry_timer and self.retry_timer.is_alive(): return
        self.retry_timer = threading.Timer(15, self.schedule); self.retry_timer.daemon = True; self.retry_timer.start()

    def schedule(self):
        if not self.running.acquire(blocking=False): return
        try:
            jobs = list(reversed(list_jobs(True)))
            for job in jobs:
                if job.get('delete_requested'): worker_command('manage.py', {'action': 'finish_abort', 'id': job['id']})
            # Several workflows may run at once; the lane broker decides from free resources, oldest first, and resumes
            # automatically paused workflows.
            pending = [job for job in jobs if not job.get('delete_requested') and not job.get('pause_requested') and job['id'] not in self.active
                       and (job.get('status') not in TERMINAL or (job.get('status') == 'PAUSED' and job.get('auto_paused_for')))]
            if not pending: return
            self._retry_later()
            if license_denial(): return
            decision = worker_command('resources.py', {'action': 'admit', 'ids': [job['id'] for job in pending], 'running': list(self.active)})
            if decision.get('status') != 200: return
            if decision.get('resumed'): self.soon(0.5); return
            following = next((job for job in pending if job['id'] == decision.get('start')), None)
            if not following: return
            self._start(following)
            self.soon(5)   # started one; consider the next shortly, after its lease registers
        except Exception:
            print('Cannot schedule worker; check data directory permissions and disk space.', file=sys.stderr, flush=True)
        finally: self.running.release()

    def _start(self, job):
        folder = job_dir(job['id'])
        with open(folder / 'working' / 'worker.log', 'ab') as log:
            try: process = spawn_security_core({'action': 'workflow', 'job_dir': str(folder)}, stdout=log, stderr=log)
            except OSError:
                current = get_job(job['id'])
                if current: worker_failure(current, 'PATH_MISSING', 'Không chạy được Python worker. Kiểm tra PYTHON_BIN và .venv.')
                return
        self.active[job['id']] = process
        threading.Thread(target=self._watch, args=(job['id'], process), daemon=True).start()

    def _watch(self, job_id, process):
        code = process.wait()
        try:
            self.active.pop(job_id, None)
            current = get_job(job_id)
            if current and current.get('delete_requested'):
                worker_command('manage.py', {'action': 'finish_abort', 'id': job_id}); self.soon(); return
            if code != 0 and current and current.get('status') not in ('FAILED', 'COMPLETED', 'CANCELLED', 'PAUSED', 'DELETING', 'AWAITING_REVIEW'):
                worker_failure(current, 'STEP_FAILED', f'Worker dừng với exit code {code}. Xem working/worker.log.')
            if code == 0 and current and current.get('status') not in ('COMPLETED', 'FAILED', 'QUEUED', 'CANCELLED', 'PAUSED', 'PARTIAL', 'DELETING', 'AWAITING_REVIEW'):
                return   # an older worker still owns this job: leave its status intact
            self.soon()
        except Exception:
            print('Cannot persist worker exit; check disk space and permissions.', file=sys.stderr, flush=True)


scheduler = Scheduler()
