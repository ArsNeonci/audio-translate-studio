"""Contract test of the app API against contracts/app-api.openapi.json.

    .venv\\Scripts\\python.exe contracts\\tests\\run_app_contract.py                 start a dev server on its own data
    .venv\\Scripts\\python.exe contracts\\tests\\run_app_contract.py --keep         keep the temporary folder afterwards

It makes a temporary data folder and licence state (never the real ones), seeds it with seed_app_data.py, starts the
app on a free port with only that data, and runs every case below. A case passes when the status code is the one
expected, the spec documents that status for the operation, the response carries Cache-Control: no-store where the
spec says x-no-store, and a JSON body matches the documented schema. At the end every documented response that is
not marked x-untested must have been produced at least once.

The licence is never ACTIVE here, so licensed operations are checked for their refusal only, and nothing is sent to
the real gateway (every gateway call needs an active licence). The YouTube session is per user, not per data folder,
so only refusals are sent to /api/settings/youtube.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from schema_check import check  # noqa: E402

SPEC = json.loads((ROOT / 'contracts' / 'app-api.openapi.json').read_text(encoding='utf-8'))
NOID = '00000000-0000-4000-8000-000000000000'
EVIL = {'Origin': 'https://evil.example'}


class Contract:
    def __init__(self, base, token):
        self.base, self.token, self.failures, self.hits, self.count = base, token, [], set(), 0

    def call(self, name, method, template, values=None, status=200, json_body=None, data=None, headers=None, params=None, expect=None):
        self.count += 1
        path = template.format(**(values or {}))
        response = requests.request(method, self.base + path, json=json_body, data=data, headers={'X-Audio-Api-Token': self.token, **(headers or {})}, params=params, timeout=300)
        problems = []
        if response.status_code != status: problems.append(f'status {response.status_code}, expected {status}: {response.text[:200]}')
        operation = SPEC['paths'].get(template, {}).get(method.lower())
        documented = (operation or {}).get('responses', {}).get(str(response.status_code))
        if operation is None: problems.append('operation not in the spec')
        elif documented is None: problems.append(f'status {response.status_code} not documented')
        else:
            self.hits.add((template, method.lower(), str(response.status_code)))
            if documented.get('x-no-store') and response.headers.get('cache-control') != 'no-store':
                problems.append(f'Cache-Control is {response.headers.get("cache-control")!r}, spec says no-store')
            schema = documented.get('content', {}).get('application/json', {}).get('schema')
            if schema and 'application/json' in response.headers.get('content-type', ''):
                problems += check(response.json(), schema, SPEC)
        if expect and not problems:
            try: expect(response)
            except AssertionError as error: problems.append(f'check failed: {error}')
        print(f'{"PASS" if not problems else "FAIL"}  {method:6} {path}  [{name}]')
        for problem in problems: print(f'        {problem}')
        if problems: self.failures.append((name, problems))
        return response

    def coverage(self):
        missing = []
        for template, item in SPEC['paths'].items():
            for method, operation in item.items():
                for code, response in operation['responses'].items():
                    if 'x-untested' not in response and (template, method, code) not in self.hits: missing.append(f'{method.upper()} {template} {code}')
        return missing


def run_cases(c, ids):
    C, Q, T, R = ids['completed'], ids['queued'], ids['tool'], ids['rule']
    v = {'id': C}

    # Billing, licence, model, quit
    c.call('billing info', 'GET', '/api/billing')
    c.call('portal home link without a licence', 'POST', '/api/billing', json_body={}, expect=lambda r: assert_eq(r.json()['mode'], 'home'))
    c.call('billing from another site', 'POST', '/api/billing', json_body={}, headers=EVIL, status=403)
    c.call('licence status', 'GET', '/api/license', expect=lambda r: assert_eq(r.json()['status'], 'UNACTIVATED'))
    c.call('machine id', 'GET', '/api/license', params={'machine': '1'}, expect=lambda r: assert_in('machine_id', r.json()))
    c.call('bad token', 'POST', '/api/license', json_body={'action': 'activate', 'token': 'x'}, status=403, expect=lambda r: assert_eq(r.json()['status'], 'INVALID'))
    c.call('unknown licence action', 'POST', '/api/license', json_body={'action': 'bogus', 'token': 'x'}, status=400)
    c.call('token too long', 'POST', '/api/license', data=json.dumps({'action': 'activate', 'token': 'x' * 34001}), status=400)
    c.call('licence from another site', 'POST', '/api/license', json_body={'action': 'activate', 'token': 'x'}, headers=EVIL, status=403)
    c.call('model state', 'GET', '/api/model', expect=lambda r: assert_eq(r.json()['phase'], 'missing'))
    c.call('model download without a licence', 'POST', '/api/model', json_body={})
    c.call('model from another site', 'POST', '/api/model', json_body={}, headers=EVIL, status=403)
    c.call('quit info', 'GET', '/api/quit', expect=lambda r: assert_eq(r.json()['installed'], False))
    c.call('quit in a checkout does nothing', 'POST', '/api/quit', json_body={}, expect=lambda r: assert_eq(r.json()['stopped'], False))
    c.call('quit from another site', 'POST', '/api/quit', json_body={}, headers=EVIL, status=403)

    # History and saved files
    c.call('history', 'GET', '/api/history', expect=lambda r: assert_eq(r.json()['total'], 3))
    c.call('history filter and page', 'GET', '/api/history', params={'status': 'COMPLETED', 'limit': '1', 'sort': 'oldest'},
           expect=lambda r: assert_eq((r.json()['total'], len(r.json()['jobs']), r.json()['jobs'][0]['id']), (1, 1, C)))
    c.call('history search miss', 'GET', '/api/history', params={'search': 'no-such-thing'}, expect=lambda r: assert_eq(r.json()['total'], 0))
    c.call('saved workflow', 'GET', '/api/history/{id}', v, expect=lambda r: assert_eq(len(r.json()['job']['files']), 9))
    c.call('unknown saved workflow', 'GET', '/api/history/{id}', {'id': NOID}, status=404)
    c.call('not a uuid', 'GET', '/api/history/{id}', {'id': 'not-an-id'}, status=404)
    f = {'id': C, 'fileId': 'ZH_MD'}
    c.call('inline file needs a licence', 'GET', '/api/history/{id}/files/{fileId}', f, status=403)
    c.call('unknown file', 'GET', '/api/history/{id}/files/{fileId}', {'id': C, 'fileId': 'NOPE'}, status=404)
    c.call('download', 'GET', '/api/history/{id}/files/{fileId}/download', f,
           expect=lambda r: assert_eq((r.headers['content-type'], r.headers['content-disposition'].split(';')[0], r.headers['accept-ranges']), ('text/markdown; charset=utf-8', 'attachment', 'bytes')))
    c.call('download range', 'GET', '/api/history/{id}/files/{fileId}/download', f, headers={'Range': 'bytes=0-3'}, status=206,
           expect=lambda r: assert_eq((len(r.content), r.headers['content-range'].split('/')[0]), (4, 'bytes 0-3')))
    c.call('range past the end', 'GET', '/api/history/{id}/files/{fileId}/download', f, headers={'Range': 'bytes=99999-'}, status=416,
           expect=lambda r: assert_eq(r.headers['content-range'].startswith('bytes */'), True))
    c.call('download preview', 'GET', '/api/history/{id}/files/{fileId}/download', f, params={'preview': '1'}, expect=lambda r: assert_eq(r.json()['offset'], 0))
    c.call('bad preview offset', 'GET', '/api/history/{id}/files/{fileId}/download', f, params={'preview': '1', 'offset': '-1'}, status=400)
    c.call('download unknown file', 'GET', '/api/history/{id}/files/{fileId}/download', {'id': C, 'fileId': 'NOPE'}, status=404)

    # Current workflows
    c.call('jobs', 'GET', '/api/jobs', expect=lambda r: assert_eq(sorted(j['id'] for j in r.json()['jobs']), sorted([C, Q, ids['queued2']])))
    c.call('completed job', 'GET', '/api/jobs/{id}', v, expect=lambda r: assert_eq(r.json()['job']['status'], 'COMPLETED'))
    c.call('queued job stays queued without a licence', 'GET', '/api/jobs/{id}', {'id': Q}, expect=lambda r: assert_eq(r.json()['job']['status'], 'QUEUED'))
    c.call('unknown job', 'GET', '/api/jobs/{id}', {'id': NOID}, status=404)
    c.call('preflight needs a licence', 'GET', '/api/jobs/preflight', status=403)
    c.call('new workflow needs a licence', 'POST', '/api/jobs', json_body={'url': 'https://youtu.be/1JzKgwOESoM'}, status=403)
    for kind, mime in (('zh', 'text/markdown'), ('vi', 'text/markdown'), ('moderated', 'text/markdown'), ('voice', 'audio/wav')):
        c.call(f'{kind} download', 'GET', '/api/jobs/{id}/artifacts/{kind}', {'id': C, 'kind': kind}, params={'download': '1'},
               expect=lambda r, mime=mime: assert_eq(r.headers['content-type'].split(';')[0], mime))
    c.call('jsonl format', 'GET', '/api/jobs/{id}/artifacts/{kind}', {'id': C, 'kind': 'vi'}, params={'download': '1', 'format': 'jsonl'},
           expect=lambda r: assert_eq(r.headers['content-type'].split(';')[0], 'application/x-ndjson'))
    c.call('inline artifact needs a licence', 'GET', '/api/jobs/{id}/artifacts/{kind}', {'id': C, 'kind': 'zh'}, status=403)
    c.call('source audio not saved', 'GET', '/api/jobs/{id}/artifacts/{kind}', {'id': C, 'kind': 'source'}, params={'download': '1'}, status=404)
    c.call('unknown artifact kind', 'GET', '/api/jobs/{id}/artifacts/{kind}', {'id': C, 'kind': 'bogus'}, status=404)
    c.call('transcript download', 'GET', '/api/jobs/{id}/transcript', v, params={'download': '1'})
    c.call('inline transcript needs a licence', 'GET', '/api/jobs/{id}/transcript', v, status=403)
    c.call('transcript of an unknown job', 'GET', '/api/jobs/{id}/transcript', {'id': NOID}, params={'download': '1'}, status=404)
    c.call('character sheet', 'GET', '/api/jobs/{id}/characters', v, expect=lambda r: assert_eq(r.json()['editable'], True))
    c.call('character sheet of an unknown job', 'GET', '/api/jobs/{id}/characters', {'id': NOID}, status=404)
    c.call('errors', 'GET', '/api/jobs/{id}/errors', v, expect=lambda r: assert_eq(r.json()['errors'], []))
    c.call('errors of an unknown job', 'GET', '/api/jobs/{id}/errors', {'id': NOID}, status=404)
    c.call('step guide', 'GET', '/api/jobs/{id}/steps/{step}', {'id': C, 'step': 'TRANSLATION'})
    c.call('unknown step', 'GET', '/api/jobs/{id}/steps/{step}', {'id': C, 'step': 'BOGUS'}, status=409)
    c.call('step guide of an unknown job', 'GET', '/api/jobs/{id}/steps/{step}', {'id': NOID, 'step': 'TRANSLATION'}, status=404)
    c.call('step retry needs a licence', 'POST', '/api/jobs/{id}/steps/{step}', {'id': C, 'step': 'TRANSLATION'}, status=403)
    for action in ('retry', 'reprocess', 'resume', 'review'):
        c.call(f'{action} needs a licence', 'POST', '/api/jobs/{id}/' + action, v, data='{}', status=403)
    for action in ('pause', 'cancel', 'abort'):
        c.call(f'{action} an unknown job', 'POST', '/api/jobs/{id}/' + action, {'id': NOID}, data='{}', status=404)
    c.call('pause a finished job', 'POST', '/api/jobs/{id}/pause', v, status=409)
    c.call('abort with a wrong number', 'POST', '/api/jobs/{id}/abort', v, json_body={'confirm': 999}, status=409)
    c.call('abort with bad JSON', 'POST', '/api/jobs/{id}/abort', v, data='{', status=400)

    # Rules
    c.call('rules', 'GET', '/api/rules', expect=lambda r: assert_eq([x['id'] for x in r.json()['rules']], [R]))
    c.call('empty source', 'POST', '/api/rules', json_body={'source': '', 'replacement': 'x'}, status=400)
    # Clients such as PowerShell's Invoke-RestMethod send this header; it must not break a forwarded route (found on the installed 1.3.0).
    c.call('Expect: 100-continue is tolerated', 'POST', '/api/rules', json_body={'source': '', 'replacement': 'x'}, headers={'Expect': '100-continue'}, status=400)
    c.call('duplicate source', 'POST', '/api/rules', json_body={'source': '谢谢', 'replacement': 'x'}, status=400)
    c.call('rule body not an object', 'POST', '/api/rules', data='[]', status=400)
    c.call('rule body not JSON', 'POST', '/api/rules', data='{', status=400)
    c.call('edit an unknown rule', 'PUT', '/api/rules/{id}', {'id': NOID}, json_body={'source': 'a', 'replacement': 'b'}, status=400)
    c.call('delete an unknown rule', 'DELETE', '/api/rules/{id}', {'id': NOID}, status=400)
    added = c.call('add a rule', 'POST', '/api/rules', json_body={'source': '你好', 'replacement': 'xin chào'}, expect=lambda r: assert_eq(len(r.json()['rules']), 2))
    new = next((x['id'] for x in added.json().get('rules', []) if x['source'] == '你好'), NOID)
    c.call('edit a rule', 'PUT', '/api/rules/{id}', {'id': new}, json_body={'source': '你好', 'replacement': 'chào'},
           expect=lambda r: assert_eq([x['replacement'] for x in r.json()['rules'] if x['id'] == new], ['chào']))
    c.call('delete a rule', 'DELETE', '/api/rules/{id}', {'id': new}, expect=lambda r: assert_eq(len(r.json()['rules']), 1))

    # Settings (compute settings live in the temporary data folder; the YouTube session does not, so only refusals)
    c.call('compute settings', 'GET', '/api/settings/compute')
    c.call('compute from another site', 'GET', '/api/settings/compute', headers=EVIL, status=403)
    c.call('unknown device', 'POST', '/api/settings/compute', json_body={'device': 'tpu'}, status=400)
    c.call('compute not JSON', 'POST', '/api/settings/compute', data='device=cpu', headers={'Content-Type': 'text/plain'}, status=415)
    c.call('compute post from another site', 'POST', '/api/settings/compute', json_body={'device': 'cpu'}, headers=EVIL, status=403)
    c.call('choose cpu', 'POST', '/api/settings/compute', json_body={'device': 'cpu'}, expect=lambda r: assert_eq(r.json()['device'], 'cpu'))
    c.call('youtube session', 'GET', '/api/settings/youtube')
    c.call('youtube from another site', 'GET', '/api/settings/youtube', headers=EVIL, status=403)
    c.call('unknown youtube action', 'POST', '/api/settings/youtube', json_body={'action': 'bogus'}, status=400)
    c.call('youtube not JSON', 'POST', '/api/settings/youtube', data='open', headers={'Content-Type': 'text/plain'}, status=415)
    c.call('youtube post from another site', 'POST', '/api/settings/youtube', json_body={'action': 'check'}, headers=EVIL, status=403)

    # Tools
    c.call('tool runs', 'GET', '/api/tools', expect=lambda r: assert_eq([j['id'] for j in r.json()['jobs']], [T]))
    c.call('tool run', 'GET', '/api/tools/{id}', {'id': T}, expect=lambda r: assert_eq(r.json()['job']['tool_type'], 'translation'))
    c.call('unknown tool run', 'GET', '/api/tools/{id}', {'id': NOID}, status=404)
    c.call('new tool run needs a licence', 'POST', '/api/tools', json_body={'tool': 'transcription', 'url': 'https://youtu.be/1JzKgwOESoM'}, status=403)
    c.call('tool output not ready', 'GET', '/api/tools/{id}/files/{fileId}', {'id': T, 'fileId': 'VI_MD'}, status=404)
    c.call('tool review needs a licence', 'POST', '/api/tools/{id}/review', {'id': T}, data='{}', status=403)

    # Voices
    listed = c.call('voices', 'GET', '/api/voices', expect=lambda r: assert_in(ids['voice'], [x['id'] for x in r.json()['voices']]))
    sample = next((x['preview_url'] for x in listed.json().get('voices', []) if x.get('preview_url')), None)
    if sample:   # samples ship pre-built in public/voice-previews
        c.call('voice sample', 'GET', '/api/voices/preview/{key}', {'key': sample.rsplit('/', 1)[1]},
               expect=lambda r: assert_eq((r.headers['content-type'], r.headers['cache-control'], r.content[:4]), ('audio/wav', 'public, max-age=31536000, immutable', b'RIFF')))
    c.call('unknown voice sample', 'GET', '/api/voices/preview/{key}', {'key': 'a' * 64}, status=404)
    c.call('bad voice sample key', 'GET', '/api/voices/preview/{key}', {'key': 'NOT-HEX'}, status=404)

    # Writes, last
    sheet = {'version': 1, 'characters': []}
    c.call('save character sheet', 'PUT', '/api/jobs/{id}/characters', v, json_body=sheet)
    c.call('invalid character sheet', 'PUT', '/api/jobs/{id}/characters', v, json_body={'characters': 'x'}, status=400)
    c.call('character sheet too large', 'PUT', '/api/jobs/{id}/characters', v, data='x' * (256 * 1024 + 1), status=413)
    c.call('character sheet of a queued job', 'PUT', '/api/jobs/{id}/characters', {'id': Q}, json_body=sheet, status=409)
    c.call('character sheet of an unknown job', 'PUT', '/api/jobs/{id}/characters', {'id': NOID}, json_body=sheet, status=404)
    c.call('pause the second queued job', 'POST', '/api/jobs/{id}/pause', {'id': ids['queued2']})
    c.call('it is paused', 'GET', '/api/jobs/{id}', {'id': ids['queued2']}, expect=lambda r: assert_eq(r.json()['job']['status'], 'PAUSED'))
    c.call('cancel the queued job', 'POST', '/api/jobs/{id}/cancel', {'id': Q})
    c.call('cancel it again', 'POST', '/api/jobs/{id}/cancel', {'id': Q}, status=409)
    c.call('abort the cancelled job', 'POST', '/api/jobs/{id}/abort', {'id': Q}, json_body={'confirm': ids['queued_no']},
           expect=lambda r: assert_eq(r.json().get('deleted'), True))
    c.call('delete history with bad JSON', 'DELETE', '/api/history/{id}', v, data='{', status=400)
    c.call('delete an unknown saved workflow', 'DELETE', '/api/history/{id}', {'id': NOID}, data='{}', status=404)
    c.call('delete the saved workflow', 'DELETE', '/api/history/{id}', v, json_body={'confirm': ids['completed_no']}, expect=lambda r: assert_eq(r.json().get('deleted'), True))
    c.call('it is gone', 'GET', '/api/history/{id}', v, status=404)
    c.call('delete a tool run with a wrong number', 'DELETE', '/api/tools/{id}', {'id': T}, json_body={'confirm': 999, 'scope': 'tools'}, status=409)
    c.call('delete a tool run with bad JSON', 'DELETE', '/api/tools/{id}', {'id': T}, data='{', status=400)
    c.call('delete an unknown tool run', 'DELETE', '/api/tools/{id}', {'id': NOID}, data='{}', status=404)
    c.call('delete the tool run', 'DELETE', '/api/tools/{id}', {'id': T}, json_body={'confirm': ids['tool_no'], 'scope': 'tools'})


def assert_eq(actual, expected):
    assert actual == expected, f'{actual!r} != {expected!r}'


def assert_in(item, collection):
    assert item in collection, f'{item!r} not in {collection!r}'


def isolated_env(work):
    return {**os.environ, 'AUDIO_DATA_DIR': str(work / 'data'), 'RESULTS_ROOT': str(work / 'data' / 'results'),
            'AUDIO_LICENSE_STATE_ROOT': str(work / 'license'), 'HY_MT_MODEL_PATH': str(work / 'no-model' / 'model.gguf'),
            'AUDIO_SHELL': '', 'NEXT_TELEMETRY_DISABLED': '1', 'PYTHONUTF8': '1'}


def start_api(work, ui=None):
    """The app's local API (worker/app_api.py) on the same temporary data, serving the built UI when `ui` is given; returns (process, url, token)."""
    import secrets
    token = secrets.token_urlsafe(32)
    log = open(work / 'api.log', 'wb')
    process = subprocess.Popen([sys.executable, str(ROOT / 'worker' / 'app_api.py'), '--port', '0', *(['--ui', str(ui)] if ui else [])], cwd=ROOT,
                               env={**isolated_env(work), 'AUDIO_API_TOKEN': token}, stdout=subprocess.PIPE, stderr=log)
    line = process.stdout.readline().decode()   # "AUDIO_API_READY <port>" once it accepts connections
    if not line.startswith('AUDIO_API_READY'): raise SystemExit(f'the local API did not start; see {work / "api.log"}')
    # Keep reading stdout into the log: an unread pipe would fill up and stop the API.
    import threading
    threading.Thread(target=lambda: [log.write(chunk) for chunk in iter(lambda: process.stdout.read(4096), b'')], daemon=True).start()
    return process, f'http://127.0.0.1:{line.split()[1]}', token


def stop_server(process):
    if os.name == 'nt': subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    else: process.terminate()
    process.wait(timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--keep', action='store_true', help='keep the temporary folder')
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='app-contract-'))
    api = None
    try:
        seeded = subprocess.run([sys.executable, str(HERE / 'seed_app_data.py'), str(work / 'data')], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        if seeded.returncode: raise SystemExit(seeded.stderr[-2000:])
        ids = json.loads(seeded.stdout.strip().splitlines()[-1])
        api = start_api(work)   # the cases call the local API directly, with its token
        contract = Contract(api[1], api[2])
        numbers = {j['id']: j['workflow_no'] for scope in ('history', 'tools') for j in requests.get(f'{contract.base}/api/{scope}', headers={'X-Audio-Api-Token': api[2]}, timeout=300).json()['jobs']}
        ids.update(completed_no=numbers[ids['completed']], queued_no=numbers[ids['queued']], tool_no=numbers[ids['tool']])
        run_cases(contract, ids)
        # The local API itself: only a caller with the per-launch token gets an answer (any other local program is refused).
        for name, headers in (('no token', {}), ('wrong token', {'X-Audio-Api-Token': 'x' * 43})):
            r = requests.get(api[1] + '/api/rules', headers=headers, timeout=60)
            ok = r.status_code == 403 and r.json() == {'error': 'API token required'} and r.headers.get('cache-control') == 'no-store'
            print(f'{"PASS" if ok else "FAIL"}  GET    <local API>/api/rules  [{name} is refused]')
            contract.count += 1
            if not ok: contract.failures.append((name, [f'{r.status_code} {r.text[:100]}']))
        missing = contract.coverage()
        print(f'\n{contract.count} cases, {len(contract.failures)} failed; documented responses never produced: {len(missing)}')
        for item in missing: print(f'  not covered: {item}')
        untested = sum('x-untested' in r for p in SPEC['paths'].values() for o in p.values() for r in o['responses'].values())
        print(f'responses marked x-untested in the spec: {untested}')
        return 1 if contract.failures or missing else 0
    finally:
        if api: stop_server(api[0])
        if args.keep: print(f'kept {work}')
        else: shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
