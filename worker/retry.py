"""Retry admission under the same OS job lock; step-scoped cleanup."""
import json
from pathlib import Path
import subprocess
import sys

from errors import STEPS, initial_steps, fix_guide, redact
from storage import DATA, LockedError, file_lock, read_json, update_job, file_digest, count_rows


def cleanup(job_dir, step):
    job_dir = Path(job_dir).resolve()
    def remove(path):
        # Never follow a link outside the job or remove a directory/input tree.
        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(job_dir):
            path.unlink()
    patterns = {
        'DOWNLOAD': ['source/*.tmp'], # .part/.ytdl belong to yt-dlp's resumable download.
        'TRANSCRIPTION': ['transcript*.tmp', 'working/chunk-*.tmp', 'working/vad*.tmp'],
        'TRANSLATION': ['transcript.vi.jsonl.tmp', 'transcript.vi.md.tmp'],
        'MODERATION': ['transcript.vi.moderated*.tmp', 'moderation-result*.tmp'],
        'TTS': ['voice/*.tmp', 'voice.vi.wav.tmp', 'voice/temp/**/*', 'working/voice-checkpoints/*.tmp'],
    }
    for pattern in patterns[step]:
        for path in job_dir.glob(pattern):
            remove(path)
    if step == 'DOWNLOAD':
        from pipeline import source_file, duration_ms
        source = source_file(job_dir)
        if source:
            try:
                if duration_ms(source) <= 0: remove(source)
            except (subprocess.CalledProcessError, ValueError):
                remove(source)
            except FileNotFoundError:
                pass  # Missing ffprobe does not prove audio corruption.
    if step == 'TRANSCRIPTION':
        canonical = job_dir/'transcript.zh.jsonl'
        try:
            count_rows(canonical, 'text')
            if not (job_dir/'transcript.zh.md').exists(): raise ValueError('Incomplete transcript')
        except (OSError, ValueError):
            for name in ['transcript.zh.jsonl', 'transcript.zh.md', 'transcript.jsonl']:
                remove(job_dir/name)
        # Chunk files are written atomically. Preserve parseable segment caches;
        # remove a malformed cache rather than failing forever on every retry.
        for chunk in (job_dir/'working').glob('chunk-*.json'):
            try:
                segments = read_json(chunk)
                if not isinstance(segments, list) or any(not isinstance(row, dict) or
                    not isinstance(row.get('text'), str) or type(row.get('start_ms')) is not int or
                    type(row.get('end_ms')) is not int for row in segments):
                    raise ValueError('Invalid chunk checkpoint')
            except (OSError, ValueError):
                remove(chunk)
    if step in STEPS[2:]:
        from postprocess import stage_complete
        try:
            valid_output = stage_complete(job_dir, step.lower())
        except (OSError, ValueError, KeyError):
            valid_output = False
        if not valid_output:
            outputs = {
                'TRANSLATION': ['transcript.vi.jsonl', 'transcript.vi.md'],
                'MODERATION': ['transcript.vi.moderated.jsonl', 'transcript.vi.moderated.md', 'moderation-result.json'],
                'TTS': ['voice.vi.wav', 'voice/voice.manifest.jsonl'],
            }
            for name in outputs[step] + [f'working/{step.lower()}.done.json']:
                remove(job_dir / name)
    if step == 'TTS':
        from postprocess import audio_info
        for meta in (job_dir/'working'/'voice-checkpoints').glob('*.json'):
            try:
                saved = read_json(meta)
                if not isinstance(saved.get('fingerprint'), str) or not isinstance(saved.get('sha256'), str):
                    raise ValueError('Invalid voice checkpoint')
            except (OSError, ValueError, AttributeError):
                remove(meta)
        for wav in (job_dir/'voice').glob('*.wav'):
            if not wav.stem.isdigit() or wav.is_symlink() or not wav.resolve().is_relative_to(job_dir):
                continue
            meta = job_dir/'working'/'voice-checkpoints'/f'{wav.stem}.json'
            try:
                saved = read_json(meta)
                valid = isinstance(saved['fingerprint'], str) and saved['sha256'] == file_digest(wav)
                if valid: audio_info(wav)
            except (OSError, ValueError, KeyError):
                valid = False
            if not valid:
                remove(wav)
                remove(meta)
    # SQLite rows, valid segment WAVs, source audio and all inputs are retained.


def request_retry(job_dir, step, fresh=False):
    from license_gate import assert_allowed
    assert_allowed()
    if step not in STEPS:
        raise ValueError('Unknown step')
    job_dir = Path(job_dir)
    with file_lock(job_dir/'working'/'worker.lock'):
        job = read_json(job_dir/'job.json')
        if (job_dir/'working'/'delete-request.json').exists(): raise ValueError('Workflow deletion is pending')
        steps = initial_steps(job)
        if job.get('status') != 'FAILED' or steps[step]['state'] != 'FAILED':
            raise ValueError('Step must be FAILED before retry')
        effective = job.get('tool_steps',STEPS)
        if step not in effective: raise ValueError('Step is not part of this tool')
        if any(steps[s]['state'] != 'COMPLETED' for s in effective[:effective.index(step)]):
            raise ValueError('Previous steps must be COMPLETED before retry')
        if any(s['state'] == 'RUNNING' for s in steps.values()) or job.get('retry_step'):
            raise ValueError('Another step instance is running or queued')
        if fresh:
            from stage_reset import reset
            reset(job_dir,step)
            steps[step].update(progress=0,started_at=None,completed_at=None,duration_ms=0,resume_duration_ms=0)
            stages=job.get('stages',{});stages.pop(step.lower(),None)
            update_job(job_dir,stages=stages)
            if step=='TRANSCRIPTION':update_job(job_dir,chunks_done=0,chunks_total=None,processed_ms=0,rows=0)
            if step=='DOWNLOAD':update_job(job_dir,duration_ms=0)
        else: cleanup(job_dir, step)
        steps[step]['state'] = 'PENDING'
        steps[step]['retry_count'] = steps[step].get('retry_count', 0) + 1
        update_job(job_dir, steps=steps, retry_step=step, status='QUEUED', error=None)
        from results import metadata
        try: metadata(job_dir)
        except (OSError, ValueError): pass  # Retry admission survives archive issues.
        return {'step': step, 'state': 'PENDING', 'retrying': True}


def main():
    try:
        payload = json.load(sys.stdin)
        job_id = payload['id']
        import re
        if not re.fullmatch(r'[0-9a-f-]{36}', job_id): raise ValueError('Invalid job ID')
        from results import workspace
        directory = workspace(job_id)
        if payload['action'] == 'retry':
            response = {'status': 202, **request_retry(directory, payload['step'],fresh=payload.get('fresh',False) is True)}
        else:
            job = read_json(directory/'job.json')
            step = payload.get('step')
            if step:
                if step not in STEPS: raise ValueError('Unknown step')
                error = initial_steps(job)[step].get('error')
                response = {'status': 200, 'error': error, 'fix_guide': fix_guide(error['error_code']) if error else None}
            else:
                path = directory/'errors.jsonl'
                # Bounded history response, newest 100 entries.
                from collections import deque
                entries = []
                if path.exists():
                    with path.open(encoding='utf-8') as handle:
                        entries = list(deque((json.loads(line) for line in handle if line.strip()), maxlen=100))
                response = {'status': 200, 'errors': entries}
    except LockedError:
        response = {'status': 409, 'error': 'Job is running in another instance.'}
    except FileNotFoundError:
        response = {'status': 404, 'error': 'Job not found.'}
    except (ValueError, KeyError) as exc:
        response = {'status': 409, 'error': redact(exc)}
    except Exception as exc:
        response = {'status': 500, 'error': redact(exc)}
    print(json.dumps(response, ensure_ascii=False))


if __name__ == '__main__': main()
