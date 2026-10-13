"""Download of the offline translation model (was lib/server/model-download.ts).

The model (4.6 GB) is not in the installer: Windows refuses executables over 4 GiB. After activation the app asks the gateway
for a one-hour signed link (valid licence only), downloads the file, and keeps it only if its size and SHA-256 equal the values
pinned below. A file that fails the check is deleted, so a wrong or tampered download is never loaded.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request

from audio_translate.api import license as lease
from audio_translate.api.runtime import license_command
from audio_translate.core.storage import ROOT

MODEL = {'id': 'hy-mt2-7b-q4km', 'file': 'Hy-MT2-7B-Q4_K_M.gguf', 'size': 4624648896,
         'sha256': '9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b'}
RETRIES, RETRY_PAUSE = 6, 3.0
STOP_AT_ONCE = ('LICENSE_REQUIRED', 'GATEWAY_NOT_CONFIGURED', 'MODEL_LINK_LIMIT', 'MODEL_DOWNLOAD_DISABLED', 'LICENSE_REVOKED', 'EXPIRED')
_claim = threading.Lock()
_holder = {'run': None, 'state': {'phase': 'missing', 'done': 0, 'total': MODEL['size']}}


class DownloadError(Exception):
    pass


def model_path():
    """The launcher points HY_MT_MODEL_PATH at the per-user data folder; a development checkout keeps its own models folder."""
    return Path(os.environ.get('HY_MT_MODEL_PATH') or ROOT / 'models' / 'Hy-MT2-7B-Q4_K_M' / MODEL['file'])


def _marker(file): return Path(f'{file}.ok')


def _mtime_ms(info): return info.st_mtime_ns // 1_000_000   # Math.trunc(mtimeMs) in Node, so markers from earlier builds stay valid


def verified_marker(file):
    """"ready" needs a marker written after the hash was checked, so a start-up does not re-hash 4.6 GB every time."""
    try:
        info, marker = file.stat(), json.loads(_marker(file).read_text(encoding='utf-8'))
        return info.st_size == MODEL['size'] and marker['size'] == info.st_size and marker['mtimeMs'] == _mtime_ms(info) and marker['sha256'] == MODEL['sha256']
    except (OSError, ValueError, KeyError, TypeError): return False


def _write_marker(file):
    info = file.stat()
    _marker(file).write_text(json.dumps({'size': info.st_size, 'mtimeMs': _mtime_ms(info), 'sha256': MODEL['sha256']}), encoding='utf-8')


def _license_status():
    try: return str(license_command({'action': 'status'}).get('status') or 'UNKNOWN')
    except Exception: return 'UNKNOWN'


def model_state():
    if _holder['run']: return dict(_holder['state'])
    if verified_marker(model_path()): return {'phase': 'ready', 'done': MODEL['size'], 'total': MODEL['size']}
    base = _holder['state'] if _holder['state']['phase'] == 'error' else {'phase': 'missing', 'done': 0, 'total': MODEL['size']}
    return {**base, 'license': _license_status()}


def _link():
    reply = license_command({'action': 'credential'})
    if reply.get('status') != 'ACTIVE' or not reply.get('token'): raise DownloadError('LICENSE_REQUIRED')
    base = lease.gateway_endpoint()
    if not base: raise DownloadError('GATEWAY_NOT_CONFIGURED')
    answer = lease.gateway_call('POST', f'{base}/v1/model/url', reply['token'], {'model': MODEL['id']})
    if answer is None: raise DownloadError('OFFLINE')
    status, body = answer
    if not 200 <= status < 300 or not body.get('url'):
        error = body.get('error') if isinstance(body.get('error'), str) else ''
        raise DownloadError(error if re.fullmatch(r'[A-Z_]{3,40}', error) else f'HTTP_{status}')
    return body['url']


def _sha256(file, report):
    digest, seen = hashlib.sha256(), 0
    with open(file, 'rb') as handle:
        while piece := handle.read(4 * 1024 * 1024):
            digest.update(piece); seen += len(piece); report(seen)
    return digest.hexdigest()


def _verifying(done): _holder['state'] = {'phase': 'verifying', 'done': done, 'total': MODEL['size']}


def _run():
    target = model_path(); partial = Path(f'{target}.part')
    target.parent.mkdir(parents=True, exist_ok=True)
    # A complete file without a marker yet (a development checkout, or a copy placed by hand) is hashed, not downloaded again.
    if target.exists() and target.stat().st_size == MODEL['size']:
        _verifying(0)
        if _sha256(target, _verifying) != MODEL['sha256']: raise DownloadError('CHECKSUM_MISMATCH')
        _write_marker(target); return
    size = lambda: partial.stat().st_size if partial.exists() else 0
    url = ''
    for attempt in range(RETRIES):
        offset = size()
        if offset == MODEL['size']: break
        if offset > MODEL['size']: partial.unlink(); offset = 0
        _holder['state'] = {'phase': 'downloading', 'done': offset, 'total': MODEL['size']}
        try:
            if not url: url = _link()
            request = urllib.request.Request(url, headers={'User-Agent': 'audio-translate-app/1', **({'Range': f'bytes={offset}-'} if offset else {})})   # Cloudflare refuses Python's default agent
            try: response = urllib.request.urlopen(request, timeout=60)
            except urllib.error.HTTPError as error:
                if error.code in (401, 403): url = ''; raise DownloadError('LINK_EXPIRED') from None
                raise DownloadError(f'HTTP_{error.code}') from None
            with response:
                if offset and response.status != 206: partial.unlink(missing_ok=True); raise DownloadError('RESUME_REFUSED')
                done, started, start_done = offset, time.monotonic(), offset
                with open(partial, 'ab' if offset else 'wb') as out:
                    while piece := response.read(256 * 1024):
                        out.write(piece); done += len(piece)
                        seconds = time.monotonic() - started
                        rate = (done - start_done) / seconds if seconds >= 1 else None
                        state = {'phase': 'downloading', 'done': done, 'total': MODEL['size']}
                        if rate: state.update(rate=rate, eta=math.ceil((MODEL['size'] - done) / rate))
                        _holder['state'] = state
        except Exception as error:
            if isinstance(error, DownloadError) and str(error) in STOP_AT_ONCE: raise
            if attempt == RETRIES - 1: raise error if isinstance(error, DownloadError) else DownloadError('OFFLINE')
            time.sleep(RETRY_PAUSE * (attempt + 1))
    if size() != MODEL['size']: raise DownloadError('INCOMPLETE')
    _verifying(0)
    if _sha256(partial, _verifying) != MODEL['sha256']: partial.unlink(missing_ok=True); raise DownloadError('CHECKSUM_MISMATCH')
    os.replace(partial, target)
    _write_marker(target)


def start_model_download():
    """One download at a time: the check and the claim happen under one lock, so two clicks never start two downloads and a
    repeated request neither asks the gateway for another link nor uses up the daily link allowance."""
    with _claim:
        if _holder['run']: return dict(_holder['state'])
        present = verified_marker(model_path())
        _holder['state'] = {'phase': 'downloading', 'done': 0, 'total': MODEL['size']}

        def work():
            try:
                if not present: _run()
                _holder['state'] = {'phase': 'ready', 'done': MODEL['size'], 'total': MODEL['size']}
            except Exception as error:
                _holder['state'] = {'phase': 'error', 'done': 0, 'total': MODEL['size'], 'error': str(error) if isinstance(error, DownloadError) else 'MODEL_DOWNLOAD_FAILED'}
            finally: _holder['run'] = None
        _holder['run'] = threading.Thread(target=work, daemon=True)
        _holder['run'].start()
        return {'phase': 'ready', 'done': MODEL['size'], 'total': MODEL['size']} if present else dict(_holder['state'])
