"""HTTP error/retry acceptance against an isolated production server."""
import argparse
import json
from pathlib import Path
import shutil
import time
import uuid

from errors import record_failure, transition
from orchestrator import migrate_steps
from storage import file_digest, file_lock, read_json, update_job
from verify_http import request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://localhost:3001')
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    import results
    results.DATA = args.data.resolve()
    results.RESULTS = results.DATA/'results'
    original = args.data/'jobs'/(args.data/'current-job.txt').read_text().strip()
    job_id = str(uuid.uuid4())
    job = args.data/'jobs'/job_id
    shutil.copytree(original, job)
    update_job(job, id=job_id, name='Error and retry acceptance')
    migrate_steps(job)
    protected = [job/n for n in ['transcript.zh.jsonl', 'transcript.vi.jsonl', 'transcript.vi.moderated.jsonl', 'voice.vi.wav']]
    protected += list((job/'voice').glob('*.wav'))
    before = {str(p): (file_digest(p), p.stat().st_mtime_ns) for p in protected}
    transition(job, 'TTS', 'RUNNING')
    record_failure(job, 'TTS', RuntimeError('CUDA out of memory\ncookie SID=never-log-this'))
    base = f'/api/jobs/{job_id}'
    def call(path, method='GET', expected=200):
        status, headers, body = request(args.base, path, method)
        assert status == expected, (path, status, body[:300])
        assert headers.get('Cache-Control') == 'no-store'
        return json.loads(body)
    for _ in range(2):
        state = call(base)['job']
        assert state['steps']['TTS']['state'] == 'FAILED'
        assert state['steps']['MODERATION']['state'] == 'COMPLETED'
    guide = call(base+'/steps/TTS')
    assert guide['error']['error_code'] == 'CUDA_OOM'
    assert guide['fix_guide']['commands'] == ['nvidia-smi']
    entries = call(base+'/errors')['errors']
    assert entries[-1]['attempt'] >= 1
    assert 'never-log-this' not in json.dumps(entries)
    with file_lock(job/'working'/'worker.lock'):
        call(base+'/steps/TTS', 'POST', 409)
    call(base+'/steps/TRANSLATION', 'POST', 409)
    call(base+'/steps/UNKNOWN', 'POST', 409)
    call(base+'/steps/TTS', 'POST', 202)
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        state = call(base)['job']
        if state['status'] in ('FAILED', 'COMPLETED'): break
        time.sleep(.2)
    assert state['status'] == 'COMPLETED', state
    assert state['steps']['TTS']['retry_count'] == 1
    assert all(s['state'] == 'COMPLETED' for s in state['steps'].values())
    assert {str(p): (file_digest(p), p.stat().st_mtime_ns) for p in protected} == before
    call(base+'/steps/TTS', 'POST', 409)
    assert call(base)['job']['steps'] == state['steps']
    # Leave this isolated fixture failed for the optional browser refresh check.
    transition(job, 'TTS', 'RUNNING')
    record_failure(job, 'TTS', RuntimeError('CUDA out of memory (UI acceptance fixture)'))
    (args.data/'error-job.txt').write_text(job_id)
    print('HTTP ERROR ACCEPTANCE OK: persisted states/history, correct guide, sanitized log, lock/invalid-state 409, step-only 202 retry, unchanged artifacts and refresh state')
    print('Browser fixture:', job_id)


if __name__ == '__main__': main()
