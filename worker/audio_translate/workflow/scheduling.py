"""Scheduler admission for simultaneous workflows (docs/MULTI_WORKFLOW_SCHEDULER.md).

The web scheduler asks which queued or automatically paused workflow may start.
Workflows are considered oldest first; an automatically paused one resumes
when its stage fits again. There is no fixed workflow limit, only resources.
"""
import json
import sys

from audio_translate.core import lanes
from audio_translate.core.errors import STEPS, initial_steps
from audio_translate.core.storage import read_json
from audio_translate.workflow import results


def next_stage(job):
    steps = initial_steps(job)
    step = job.get('retry_step') or next((s for s in job.get('tool_steps', STEPS) if steps[s]['state'] != 'COMPLETED'), 'TTS')
    return step.lower()


def admit(ids, running=()):
    candidates = []
    for job_id in ids:
        try:
            job = read_json(results.workspace(job_id) / 'job.json')
        except (OSError, ValueError, KeyError):
            continue
        if job['status'] == 'PAUSED' and not job.get('auto_paused_for'):
            continue  # a user pause is never resumed automatically
        candidates.append({**job, '_next_stage': next_stage(job)})
    start, resume, reasons = lanes.admission([job for job in candidates if job['id'] not in set(running)])
    resumed = None
    if resume:
        from audio_translate.workflow.manage import resume as resume_job
        resume_job(resume['id'])
        resumed = resume['id']
    return {'status': 200, 'start': start['id'] if start else None, 'resumed': resumed, 'reasons': reasons}


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get('action') != 'admit':
            result = {'status': 400, 'error': 'Invalid action'}
        else:
            result = admit([str(value) for value in payload.get('ids', [])], payload.get('running', []))
    except Exception as exc:  # the scheduler retries on its next pass
        result = {'status': 503, 'error': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
