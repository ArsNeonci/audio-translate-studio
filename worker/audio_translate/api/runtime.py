"""How the API reaches the worker scripts and the native security core (the Python side of lib/server/python.ts,
worker-client.ts, security-core.ts and license.ts).

Nothing changes about the security boundary: manage.py and retry.py still run only through the security core (which checks
integrity and the licence gate per action), every other script runs as its own process exactly as Next.js started it.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from audio_translate.core import secure_channel
from audio_translate.core.storage import DATA, ROOT
from audio_translate.workflow.results import RESULTS

WORKER = ROOT / 'worker'
BROKERED = ('manage.py', 'retry.py')
SCRIPTS = ('rules.py', 'retry.py', 'results.py', 'manage.py', 'youtube_session.py', 'compute_settings.py', 'resources.py')
OUTPUT_LIMIT = 16 * 1024 * 1024


class WorkerError(Exception):
    """A worker script could not answer (start failure, timeout, exit code, unreadable output)."""


def python_bin():
    venv = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return os.environ.get('PYTHON_BIN') or (str(venv) if venv.exists() else sys.executable)


def worker_env():
    env = {k: v for k, v in os.environ.items() if k != 'AUDIO_API_TOKEN'}   # the API's own secret stays in this process
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', AUDIO_DATA_DIR=str(DATA), RESULTS_ROOT=str(RESULTS),
               MODELSCOPE_CACHE=os.environ.get('MODELSCOPE_CACHE') or str(DATA / 'model-cache'),
               HF_HOME=os.environ.get('HF_HOME') or str(DATA / 'hf-cache'))
    return env


def security_core_bin():
    return ROOT / 'security-core' / 'bin' / 'audio-security-core.exe'


def spawn_security_core(payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE):
    """Start the security core with one JSON request on stdin (the caller reads its answer or lets it run)."""
    process = subprocess.Popen([str(security_core_bin())], cwd=ROOT, env=worker_env(), stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        process.stdin.write(json.dumps(payload).encode()); process.stdin.close()
    except OSError: pass
    return process


def worker_command(script, payload):
    """Run one worker command and return its JSON answer, as worker-client.ts pythonCommand did."""
    if script not in SCRIPTS: raise WorkerError('unknown script')
    timeout = 300 if script in ('results.py', 'manage.py') else 60 if script == 'youtube_session.py' else 40
    if script in BROKERED:
        process = spawn_security_core({'action': 'command', 'script': script, 'payload': payload})
    else:
        process = subprocess.Popen([python_bin(), str(WORKER / script)], cwd=ROOT, env=worker_env(), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            process.stdin.write(json.dumps(payload).encode()); process.stdin.close()
        except OSError: pass
    try:
        out, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill(); process.communicate(); raise WorkerError('Worker service timed out') from None
    if len(out) > OUTPUT_LIMIT: raise WorkerError('Metadata response too large')
    if process.returncode != 0: raise WorkerError('worker failed')
    try: return json.loads(out)
    except ValueError: raise WorkerError('Invalid worker response') from None


def call_security_core(payload, timeout=40):
    return secure_channel.call(payload, timeout_ms=int(timeout * 1000))


def license_command(payload):
    """Ask the service over its pipe; without the service (development) run the core binary once, as license.ts did."""
    try: return call_security_core(payload)
    except Exception: pass
    unavailable = {'http_status': 503, 'status': 'INVALID', 'error': 'License service unavailable.'}
    try:
        process = spawn_security_core(payload)
        out, _ = process.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        process.kill(); process.communicate(); return unavailable
    except OSError: return unavailable
    if process.returncode or len(out) > 65536: return unavailable
    try: return json.loads(out)
    except ValueError: return unavailable


_edition = None


def edition():
    """basic or plus, from the Product ID compiled into the core (edition.ts)."""
    global _edition
    if _edition: return _edition
    value = license_command({'action': 'identity'})
    if value.get('http_status') != 200 or not value.get('product_id'): return 'basic'
    tier = value.get('tier') or ('basic' if value['product_id'].endswith('-basic') else 'plus')
    _edition = 'plus' if tier == 'plus' else 'basic'
    return _edition
