"""End-to-end run of real work through the whole app: browser-style requests -> web server -> local API -> scheduler ->
security core -> worker processes. Uses the machine's real licence (it must be ACTIVE) but a temporary data folder, so the
owner's History is not touched; model caches come from the development data folder.

    .venv\\Scripts\\python.exe contracts\\tests\\e2e_tools.py

1. a moderation tool run applies a replacement rule (no model);
2. a TTS tool run makes a voice from one short line (VieNeu on CPU);
3. a queued run is paused and resumed;
4. the worker process of a TTS run is killed: the scheduler must record STEP_FAILED, and retrying the step must finish.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

import psutil
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_app_contract as harness  # noqa: E402

ROOT = harness.ROOT
ISOLATED_ENV = harness.isolated_env   # the original; main() swaps the harness's copy for env_for
TERMINAL = ('COMPLETED', 'FAILED', 'CANCELLED', 'PAUSED', 'PARTIAL', 'AWAITING_REVIEW')
failures = []


def check(name, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  ({detail})' if detail and not ok else ''))
    if not ok: failures.append(name)


def env_for(work):
    env = ISOLATED_ENV(work)
    env.pop('AUDIO_LICENSE_STATE_ROOT')   # the real licence
    dev = ROOT / 'data'
    env.update(HF_HOME=str(dev / 'hf-cache'), MODELSCOPE_CACHE=str(dev / 'model-cache'))
    return env


def main():
    work = Path(tempfile.mkdtemp(prefix='app-e2e-'))
    (work / 'data').mkdir()
    api = None
    original = harness.isolated_env
    harness.isolated_env = env_for   # start_api / start_server build their environment from it
    try:
        api = harness.start_api(work)
        base = api[1]
        http = requests.Session()
        http.headers['X-Audio-Api-Token'] = api[2]
        get = lambda path: http.get(base + path, timeout=300)
        licence = get('/api/license').json()
        if licence.get('status') != 'ACTIVE': raise SystemExit(f'the licence is {licence.get("status")}: an ACTIVE licence is needed')

        def upload(tool, lines, extra=''):
            r = http.post(f'{base}/api/tools?tool={tool}&name=input.txt{extra}', data='\n'.join(lines).encode(), headers={'Content-Type': 'text/plain'}, timeout=300)
            if r.status_code != 201: raise SystemExit(f'{tool}: {r.status_code} {r.text}')
            return r.json()['job']['id']

        def wait(job_id, until=TERMINAL, timeout=900):
            deadline = time.time() + timeout
            while time.time() < deadline:
                get('/api/tools')   # lets the scheduler run, as the page's polling does
                job = get(f'/api/tools/{job_id}').json().get('job') or {}
                if job.get('status') in until: return job
                time.sleep(2)
            return job

        # 1. Moderation with a rule: no model, all through the scheduler and the security core.
        http.post(f'{base}/api/rules', json={'source': 'chao ban', 'replacement': 'xin chào bạn'}, timeout=60)
        job_id = upload('moderation', ['chao ban, hôm nay thế nào?', 'Tôi ổn.'])
        job = wait(job_id, timeout=300)
        check('moderation tool completes', job.get('status') == 'COMPLETED', job.get('status'))
        moderated = next((f for f in job.get('files', []) if f['type'] == 'MODERATED_MD'), None)
        text = get(f'/api/tools/{job_id}/files/{moderated["id"]}?download=1').text if moderated else ''
        check('the rule was applied in the saved output', 'xin chào bạn' in text and 'chao ban' not in text, text[:80])

        # 2. TTS from one short line.
        tts_id = upload('tts', ['Xin chào, đây là một câu thử ngắn.'])
        job = wait(tts_id)
        check('TTS tool completes', job.get('status') == 'COMPLETED', f"{job.get('status')} {job.get('error')}")
        voice = next((f for f in job.get('files', []) if f['type'] == 'VOICE_WAV'), None)
        audio = http.get(f'{base}/api/tools/{tts_id}/files/{voice["id"]}?download=1', timeout=300).content if voice else b''
        check('the voice is a WAV file', audio[:4] == b'RIFF' and len(audio) > 10000, f'{len(audio)} bytes')

        # 3. Pause a run right after it is queued, then resume it.
        paused_id = upload('moderation', ['chao ban.'])
        r = http.post(f'{base}/api/jobs/{paused_id}/pause', timeout=300)
        job = wait(paused_id, timeout=120)
        if job.get('status') == 'COMPLETED':
            print('NOTE  the run finished before the pause reached it; pause/resume not exercised')
        else:
            check('pause stops the run', r.status_code == 200 and job.get('status') == 'PAUSED', f'{r.status_code} {job.get("status")}')
            r = http.post(f'{base}/api/jobs/{paused_id}/resume', timeout=300)
            check('resume is accepted', r.status_code == 200, r.text[:120])
            job = wait(paused_id, timeout=300)
            check('the resumed run completes', job.get('status') == 'COMPLETED', job.get('status'))

        # 4. Kill the worker of a TTS run: the scheduler records STEP_FAILED; retrying the step finishes it.
        killed_id = upload('tts', ['Câu thứ nhất để thử dừng tiến trình.', 'Câu thứ hai.', 'Câu thứ ba.'])
        job = wait(killed_id, until=('TTS_GENERATING', *TERMINAL), timeout=600)
        # On Windows the venv's python.exe is a launcher, so the API itself is a grandchild: search the whole tree.
        api_process = psutil.Process(api[0].pid)
        cores = [p for p in api_process.children(recursive=True) if 'audio-security-core' in (p.name() or '').lower()]
        if job.get('status') != 'TTS_GENERATING' or not cores:
            print(f"NOTE  could not catch the run while it worked ({job.get('status')}, {len(cores)} core processes); the kill test was skipped")
            wait(killed_id)
        else:
            for process in cores:
                for child in process.children(recursive=True): child.kill()
                process.kill()
            job = wait(killed_id, until=('FAILED', 'COMPLETED'), timeout=120)
            step = (job.get('steps') or {}).get('TTS') or {}
            check('a killed worker is recorded as STEP_FAILED', job.get('status') == 'FAILED' and (step.get('error') or {}).get('error_code') == 'STEP_FAILED',
                  f"{job.get('status')} {(step.get('error') or {}).get('error_code')}")
            r = http.post(f'{base}/api/jobs/{killed_id}/steps/TTS', timeout=300)
            check('retrying the step is accepted', r.status_code == 202, f'{r.status_code} {r.text[:120]}')
            job = wait(killed_id)
            check('the retried run completes', job.get('status') == 'COMPLETED', f"{job.get('status')} {job.get('error')}")

        quit_info = get('/api/quit').json()
        check('no workflow process is left running', quit_info.get('active_jobs') == 0, str(quit_info))
        print(f'\n{len(failures)} failed' + (f': {failures}' if failures else ''))
        return 1 if failures else 0
    finally:
        harness.isolated_env = original
        if api: harness.stop_server(api[0])
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
