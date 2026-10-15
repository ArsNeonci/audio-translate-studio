"""Persisted step states, sanitized failures and non-executing fix guides."""
from datetime import datetime, timezone
import errno
import json
import os
import re
from pathlib import Path

from audio_translate.core.storage import atomic_json, read_json, update_job

STEPS = ['DOWNLOAD', 'TRANSCRIPTION', 'TRANSLATION', 'MODERATION', 'TTS']
# Three optional steps follow Voice generation. SUBTITLE (the .srt of the voice) is part of every workflow created from 3.1.0 on (its settings are
# stored in job['subtitle']), of tool 5, and of an older workflow once Reprocess asks for it. VIDEO (video merge) only exists for runs that have
# videos (a workflow with videos chosen, or tool 6). BURN (the subtitles drawn into a second video) exists only when it was ticked
# (job['video']['burn']) and always follows VIDEO. A run without the key never shows the step.
SUBTITLE = 'SUBTITLE'
VIDEO = 'VIDEO'
BURN = 'BURN'
OPTIONAL = (SUBTITLE, VIDEO, BURN)
ALL_STEPS = [*STEPS, *OPTIONAL]


def effective_steps(job):
    """The steps this run goes through, in order."""
    if job.get('tool_steps'): return list(job['tool_steps'])
    video = job.get('video')
    return [*STEPS, *(SUBTITLE,) * (job.get('subtitle') is not None), *(VIDEO,) * bool(video), *(BURN,) * bool(video and video.get('burn'))]
# One entry per code the program knows: what happened, what to do (from error_ids.py; no paths, commands or settings names).
from audio_translate.core import error_ids
GUIDES = {code: (error_ids.ERRORS[eid][0], '', [error_ids.ERRORS[eid][1]], []) for code, eid in error_ids.CODE_IDS.items() if eid in error_ids.ERRORS}


def redact(message):
    text = str(message)
    for key, value in os.environ.items():
        if value and re.search(r'token|password|secret|api.?key|cookie|authorization|credential', key, re.I):
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'https?://[^\s]+', '[URL]', text)
    text = re.sub(r'(?im)^.*(?:cookie|authorization|bearer|password|secret|token|api[_-]?key|\bSID=|\bSAPISID=).*$','[Sensitive detail removed]', text)
    text = re.sub(r'\b[\w-]{2,}=[^\s;,]+', '[REDACTED]', text)
    return text[:2000]


def classify(exc):
    if getattr(exc, 'error_id', None) in error_ids.ERRORS:
        return next((code for code, eid in error_ids.CODE_IDS.items() if eid == exc.error_id), exc.error_id)
    if getattr(exc, 'code', None) in {'UNACTIVATED','EXPIRED','CLOCK_ROLLBACK','TRUSTED_TIME_UNAVAILABLE','WRONG_MACHINE','INVALID','RENEWAL_REQUIRED'}:
        return exc.code
    if getattr(exc, 'code', None) == 'VOICE_MISSING': return 'VOICE_MISSING'
    if type(exc).__name__ == 'VideoError':
        return {'VIDEO_TYPE': 'VIDEO_UNREADABLE', 'VIDEO_INVALID': 'VIDEO_UNREADABLE'}.get(exc.code, exc.code)
    message = str(exc).lower()
    number = getattr(exc, 'errno', None)
    if type(exc).__name__ == 'YouTubeSessionError': code = 'YOUTUBE_AUTH'
    elif isinstance(exc, ModuleNotFoundError): code = 'DEPENDENCY_MISSING'
    elif number == errno.ENOSPC or getattr(exc, 'winerror', None) == 112 or 'no space left' in message or 'disk full' in message: code = 'DISK_FULL'
    elif isinstance(exc, PermissionError): code = 'FILE_PERMISSION'
    elif 'out of memory' in message and 'cuda' in message: code = 'CUDA_OOM'
    elif any(word in message for word in ['cuda', 'not compiled with', 'invalid device']): code = 'CUDA_CONFIG'
    elif any(word in message for word in ['cookie', 'sign in', 'xác thực']): code = 'YOUTUBE_AUTH'
    elif '429' in message: code = 'RATE_LIMIT'
    elif any(word in message for word in ['ffmpeg', 'ffprobe']) and isinstance(exc, FileNotFoundError): code = 'FFMPEG_MISSING'
    elif any(word in message for word in ['model', 'vieneu', 'trọng số', 'tokenizer', 'weights']) and ('not found' in message or 'không tìm' in message or 'load' in message): code = 'MODEL_MISSING'
    elif isinstance(exc, FileNotFoundError): code = 'PATH_MISSING'
    elif isinstance(exc, ValueError) and any(word in message for word in ['invalid literal', 'environment', 'device', 'batch', 'results_root']): code = 'ENV_CONFIG'
    else: code = 'STEP_FAILED'
    return code


def identify(exc):
    """The short ID of a failure: the one it carries, else the one of its code, else X900."""
    if getattr(exc, 'error_id', None) in error_ids.ERRORS: return exc.error_id
    return error_ids.CODE_IDS.get(classify(exc), 'X900')


def fix_guide(code):
    if code not in GUIDES:
        return None
    cause, config, instructions, commands = GUIDES[code]
    return {'cause': cause, 'config': config, 'checks_and_fixes': instructions, 'commands': commands}


def initial_steps(job):
    wanted = effective_steps(job)
    names = [*STEPS, *(s for s in OPTIONAL if s in wanted or s in job.get('steps', {}))]
    steps = {step: {'state': 'PENDING', 'retry_count': 0, 'attempt': 0, 'progress':0,
                    'started_at':None,'completed_at':None,'duration_ms':None} for step in names}
    for step, item in job.get('steps', {}).items():
        if step in steps: steps[step].update(item)
    return steps


def transition(job_dir, step, state):
    job = read_json(Path(job_dir)/'job.json')
    steps = initial_steps(job)
    item = steps[step]
    from audio_translate.core.control import now, elapsed
    stamp = now()
    if state == 'RUNNING':
        item.update(started_at=stamp,completed_at=None,duration_ms=item.get('resume_duration_ms',0),progress=None)
        item.pop('error',None)
    elif state in ['COMPLETED','FAILED','CANCELLED','PAUSED']:
        item.update(completed_at=stamp,duration_ms=item.get('resume_duration_ms',0)+elapsed(item.get('started_at'),stamp))
        if state == 'COMPLETED': item['progress'] = 100
    item['state'] = state
    if state == 'RUNNING':
        item['attempt'] = item.get('attempt', 0) + 1
    if state == 'COMPLETED':
        item.pop('error', None)
    stages = job.get('stages',{})
    if state == 'RUNNING': stages[step.lower()] = {'percent':None,'done':0,'total':None}
    elif state == 'COMPLETED': stages[step.lower()] = {**stages.get(step.lower(),{}),'percent':100}
    effective = effective_steps(job)
    values = [100 if steps[s]['state']=='COMPLETED' else stages.get(s.lower(),{}).get('percent',0) for s in effective]
    overall = None if any(v is None for v in values) else round(sum(values)/len(values),2)
    update_job(job_dir, steps=steps, stages=stages, progress=overall)


def record_failure(job_dir, step, exc):
    job_dir = Path(job_dir)
    job = read_json(job_dir/'job.json')
    steps = initial_steps(job)
    item = steps[step]
    code = classify(exc)
    timestamp = datetime.now(timezone.utc).isoformat()
    error_id = identify(exc)
    # The person sees the sentence and the ID; the raw text of the failure stays in errors.jsonl.
    failure = {'step': step, 'error_code': code, 'error_id': error_id, 'error_message': error_ids.message(error_id), 'error_type': type(exc).__name__,
               'recoverable_manually': code in GUIDES, 'failed_at': timestamp, 'retry_count': item.get('retry_count', 0)}
    from audio_translate.core.control import now, elapsed, end_run
    item.update(state='FAILED', error=failure, completed_at=now(), duration_ms=item.get('resume_duration_ms',0)+elapsed(item.get('started_at')))
    end_run(job_dir,'FAILED')
    update_job(job_dir, steps=steps, status='FAILED', failed_stage=step.lower(), active_stage=None,
               retry_step=None, error=failure['error_message'])
    entry = {**failure, 'attempt': item.get('attempt', 1), 'message': failure['error_message'], 'detail': redact(getattr(exc, 'detail', '') or exc), 'timestamp': timestamp}
    with (job_dir/'errors.jsonl').open('a', encoding='utf-8') as out:
        out.write(json.dumps(entry, ensure_ascii=False)+'\n')
        out.flush()
        os.fsync(out.fileno())
    try:
        from audio_translate.workflow.results import metadata
        metadata(job_dir)
    except (OSError, ValueError):
        pass  # The workspace failure survives even when result storage is full.
    return failure
