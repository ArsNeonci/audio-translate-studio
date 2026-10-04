"""One job lock, isolated model processes, durable per-stage resume."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from audio_translate.core.control import check_cancel, Cancelled, cancel_run, now, end_run
from audio_translate.core.errors import STEPS, initial_steps, transition, record_failure, redact
from audio_translate.workflow.results import publish_step, metadata, cleanup_temporary
from audio_translate.core.storage import (DATA, ROOT, LockedError, count_rows, file_lock,
                     progress, read_json, update_job)


def prepare_transcript(job_dir):
    canonical = job_dir / "transcript.zh.jsonl"
    legacy = job_dir / "transcript.jsonl"
    if not canonical.exists() and legacy.exists() and (job_dir / "transcript.zh.md").exists():
        temp = canonical.with_suffix(".jsonl.tmp")
        shutil.copyfile(legacy, temp)
        os.replace(temp, canonical)
    if not canonical.exists() or not (job_dir / "transcript.zh.md").exists():
        return False
    count = count_rows(canonical, "text")
    progress(job_dir, "transcription", "TRANSCRIPTION_COMPLETED", count, count)
    return True


def run_stage(job_dir, stage):
    from audio_translate.core.license_gate import assert_allowed
    assert_allowed()
    from audio_translate.core.compute_settings import freeze, validate, stage_environment
    device = freeze(job_dir)
    validate(device, [stage])
    os.environ.update(stage_environment(device))
    if stage in ('download', 'transcription'):
        required = ['ffprobe'] if stage == 'download' else ['ffmpeg', 'ffprobe']
        for binary in required:
            if not shutil.which(binary):
                raise FileNotFoundError(f'{binary} is missing from PATH')
    if stage == "download":
        from audio_translate.transcription.pipeline import download, duration_ms
        source = download(job_dir)
        measured = duration_ms(source)
        if measured <= 0:
            raise ValueError('Downloaded audio has no valid duration')
        update_job(job_dir, duration_ms=measured)
        progress(job_dir, 'download', 'DOWNLOADING', 1, 1)
    elif stage == "transcription":
        from audio_translate.transcription.pipeline import source_file, vad_pass, make_chunks, transcribe, merge
        source = source_file(job_dir)
        if source is None:
            raise FileNotFoundError("Completed download audio is missing")
        total = read_json(job_dir / "job.json")["duration_ms"]
        from audio_translate.transcription.transcription_progress import phase
        working = job_dir / 'working'
        with phase(job_dir, 1, cached=(working/'vad.done').exists() and (working/'vad.jsonl').exists()):
            vad_pass(job_dir, source, total)
        with phase(job_dir, 2, cached=(working/'chunks.json').exists()):
            chunks = make_chunks(job_dir)
        with phase(job_dir, 3, cached=all((working/f'chunk-{i:06d}.json').exists() for i in range(len(chunks)))):
            transcribe(job_dir, source, chunks)
        with phase(job_dir, 4):
            merge(job_dir, chunks)
            if not prepare_transcript(job_dir):
                raise RuntimeError("Transcription did not produce the canonical Chinese files")
    else:
        from audio_translate.workflow.postprocess import translate, moderate, synthesize
        {"translation": translate, "moderation": moderate, "tts": synthesize}[stage](job_dir)


def migrate_steps(job_dir):
    job = read_json(job_dir / "job.json")
    if "steps" in job:
        return
    steps = initial_steps(job)
    from audio_translate.transcription.pipeline import source_file
    if source_file(job_dir): steps["DOWNLOAD"]["state"] = "COMPLETED"
    if prepare_transcript(job_dir):
        steps["DOWNLOAD"]["state"] = "COMPLETED"
        steps["TRANSCRIPTION"]["state"] = "COMPLETED"
        from audio_translate.workflow.postprocess import stage_complete
        for step in STEPS[2:]:
            if stage_complete(job_dir, step.lower()): steps[step]["state"] = "COMPLETED"
    update_job(job_dir, steps=steps)


def run(job_dir):
    from audio_translate.core.license_gate import assert_allowed
    job_dir = Path(job_dir).resolve()
    (job_dir / "working").mkdir(parents=True, exist_ok=True)
    from audio_translate.core.lanes import Lease
    with file_lock(job_dir / "working" / "worker.lock"), Lease(job_dir) as lease:
        current_step = "DOWNLOAD"
        update_job(job_dir, auto_paused_for=None, auto_paused_at=None)
        try:
            job = read_json(job_dir / 'job.json')
            current_step = job.get('retry_step') or next((step for step in job.get('tool_steps', STEPS) if initial_steps(job)[step]['state'] != 'COMPLETED'), 'TTS')
            check_cancel(job_dir)
            assert_allowed()
            from audio_translate.core.compute_settings import freeze, validate, stage_environment
            device = freeze(job_dir)
            effective = job.get('tool_steps', STEPS)
            pending = [s for s in effective if initial_steps(job)[s]['state'] != 'COMPLETED']
            validate(device, [job['retry_step']] if job.get('retry_step') else pending)
            update_job(job_dir, started_at=job.get('started_at') or now(), run_started_at=now(), completed_at=None)
            migrate_steps(job_dir)
            update_job(job_dir, workflow_version=2, error=None)
            metadata(job_dir)
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "HF_HOME": os.getenv("HF_HOME", str(DATA / "hf-cache")), "AUDIO_ACTIVE_JOB":str(job_dir)}
            env.update(stage_environment(device))
            requested = read_json(job_dir / "job.json").get("retry_step")
            effective = read_json(job_dir / "job.json").get("tool_steps",STEPS)
            steps_to_run = [requested] if requested else effective
            for step in steps_to_run:
                current_step = step
                check_cancel(job_dir)
                job = read_json(job_dir / "job.json")
                state = initial_steps(job)[step]['state']
                if state == 'COMPLETED':
                    publish_step(job_dir, step)
                    continue
                if any(initial_steps(job)[s]['state'] != 'COMPLETED' for s in effective[:effective.index(step)]):
                    raise RuntimeError("Previous steps must be completed")
                if step in STEPS[2:]:
                    from audio_translate.workflow.postprocess import stage_complete
                    if stage_complete(job_dir, step.lower()):
                        publish_step(job_dir, step)
                        transition(job_dir, step, 'COMPLETED')
                        metadata(job_dir)
                        continue
                transition(job_dir, step, 'RUNNING')
                statuses = {'DOWNLOAD': 'DOWNLOADING', 'TRANSCRIPTION': 'TRANSCRIBING', 'TRANSLATION': 'TRANSLATING', 'MODERATION': 'MODERATING', 'TTS': 'TTS_GENERATING'}
                update_job(job_dir, active_stage=step.lower(), status=statuses[step])
                metadata(job_dir)
                lease.stage(step.lower())
                result = subprocess.run([sys.executable, str(ROOT/'worker'/'orchestrator.py'), str(job_dir), "--stage", step.lower()], env=env)
                lease.stage(None)
                check_cancel(job_dir)
                if result.returncode:
                    job = read_json(job_dir / "job.json")
                    if initial_steps(job)[step]['state'] != 'FAILED':
                        record_failure(job_dir, step, RuntimeError(f"Worker exited with code {result.returncode}"))
                    return 1
                publish_step(job_dir, step)
                transition(job_dir, step, 'COMPLETED')
                metadata(job_dir)
            job = read_json(job_dir / 'job.json')
            all_done = all(initial_steps(job)[s]['state'] == 'COMPLETED' for s in effective)
            # Retry executes exactly the failed node. Pending successors continue
            # on the next ordinary scheduling pass, never rerunning predecessors.
            update_job(job_dir, status='COMPLETED' if all_done else 'QUEUED',
                       retry_step=None, active_stage=None, failed_stage=None, error=None)
            if all_done:
                end_run(job_dir,'COMPLETED')
                update_job(job_dir, progress=100, reprocess_pending=False)
            metadata(job_dir)
            if all_done: cleanup_temporary(job_dir)
            return 0
        except Cancelled:
            cancel_run(job_dir,current_step)
            return 0
        except Exception as exc:
            if (job_dir/'working'/'cancel.signal').exists():
                cancel_run(job_dir,current_step)
                return 0
            try: record_failure(job_dir, current_step, exc)
            except OSError: print('Cannot persist failure; check disk space and write permissions.', file=sys.stderr)
            return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--stage", choices=["download", "transcription", "translation", "moderation", "tts"])
    args = parser.parse_args()
    try:
        if args.stage:
            run_stage(args.job_dir, args.stage)
            return 0
        return run(args.job_dir)
    except Cancelled:
        cleanup_temporary(args.job_dir)
        return 2
    except LockedError as exc:
        if not args.stage:
            return 0
        record_failure(args.job_dir, args.stage.upper(), exc)
        return 1
    except Exception as exc:
        stage = args.stage or read_json(args.job_dir / "job.json").get("active_stage") or "download"
        try: record_failure(args.job_dir, stage.upper(), exc)
        except OSError: print('Cannot persist failure; check disk space and permissions.', file=sys.stderr)
        print(redact(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
