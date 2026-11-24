"""Monthly paid-until date of this device, published by the owner in status.json on GitHub Pages (no server needed).

status.json sits next to endpoint.json in every place of genius.json `directory`:
    {"serial": 12, "updated": "...", "strict": false, "message": "...", "devices": {"<device code>": "2026-12-16T16:59:59Z", ...}}
The device code is the first 16 hex characters of SHA-256(machine id), so the public file names no customer. The app keeps the last date it read in
data/license/paid-until.json and stops new work when that date has passed, online or not; a work already running goes on. A device the file does not
list may work (while customers are being moved), unless the file says "strict": true.

Time: the date is compared with the newest of this PC's clock and the server time seen in earlier reads (HTTP Date header) plus the time elapsed since,
and that point never goes backwards, so setting the PC clock back does not stretch the paid period. The owner's page and the runbook are in the private
repository (docs/PLAN_GITHUB_LICENCE_HUB.md). Security is deliberately modest: customers are not expected to tamper with the app.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
import threading
import time
import urllib.request

from audio_translate.core import endpoint as address_book
from audio_translate.core.storage import DATA, atomic_json

NAME = 'status.json'
CHECK_SECONDS, BLOCKED_CHECK_SECONDS = 4 * 3600, 15 * 60   # how often the file is read: normally, and while this device is locked
NOTICE_DAYS = 5                                           # the reminder shows this many days before the date
FETCH_TIMEOUT, MAX_BYTES = 5, 512 * 1024
CODE = re.compile(r'[0-9a-f]{16}')
_lock, _busy = threading.Lock(), threading.Lock()


def path(): return DATA / 'license' / 'paid-until.json'


def device_code(machine_id):
    return hashlib.sha256(str(machine_id).strip().lower().encode()).hexdigest()[:16]


def _stamp(text):
    try: value = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError: return None
    return value.timestamp() if value.tzinfo else None


def load():
    try: value = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}
    return value if isinstance(value, dict) else {}


def now(saved=None, local=None):
    """The time the date is compared with: never earlier than the newest moment already seen (local clock or server Date)."""
    saved = load() if saved is None else saved
    local = time.time() if local is None else local
    seen, at = float(saved.get('server_time') or 0), float(saved.get('server_seen_local') or 0)
    from_server = seen + max(0.0, local - at) if seen else 0.0
    return max(local, from_server, float(saved.get('max_time') or 0))


def parse(raw):
    """The useful part of status.json, or ValueError."""
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('serial'), int) or not isinstance(data.get('devices', {}), dict): raise ValueError('status')
    devices = {}
    for code, until in data.get('devices', {}).items():
        stamp = _stamp(until)
        if CODE.fullmatch(str(code)) and stamp is not None: devices[code] = stamp
    message = data.get('message') if isinstance(data.get('message'), str) else ''
    return {'serial': data['serial'], 'strict': data.get('strict') is True, 'message': message[:500], 'devices': devices}


def _read(base, opener=None):
    request = urllib.request.Request(f'{base}/{NAME}', headers={'User-Agent': 'audio-translate-app/1', 'Cache-Control': 'no-cache'})
    with (opener or urllib.request.urlopen)(request, timeout=FETCH_TIMEOUT) as response:
        raw = response.read(MAX_BYTES + 1)
        date = response.headers.get('Date') if getattr(response, 'headers', None) else None
    if len(raw) > MAX_BYTES: raise ValueError('size')
    try: server = parsedate_to_datetime(date).timestamp() if date else None
    except (TypeError, ValueError): server = None
    return parse(raw), server


def refresh(machine_id, opener=None, local=None):
    """Read the file from every place, keep the highest serial, save what concerns this device. {'ok': bool, 'serial'}."""
    local = time.time() if local is None else local
    best, server = None, None
    for base in address_book.mirrors():
        try: found, date = _read(base, opener)
        except Exception: continue
        if date: server = max(server or 0, date)
        if best is None or found['serial'] > best['serial']: best = found
    with _lock:
        saved = load()
        state = {**saved, 'checked_at': local}
        if server: state.update(server_time=server, server_seen_local=local)
        if best is not None and best['serial'] >= int(saved.get('serial') or 0):   # an older copy (a mirror that lags) never undoes a newer one
            code = device_code(machine_id)
            state.update(ok_at=local, serial=best['serial'], strict=best['strict'], message=best['message'], code=code,
                         listed=code in best['devices'], valid_until=best['devices'].get(code))
        state['max_time'] = now(state, local)
        path().parent.mkdir(parents=True, exist_ok=True); atomic_json(path(), state)
    return {'ok': best is not None, 'serial': state.get('serial')}


def state(machine_id=None, local=None):
    """What the app shows: status OK, DUE_SOON, OVERDUE or UNMANAGED, the date, days left, the owner's message and the device code."""
    saved = load()
    code = device_code(machine_id) if machine_id else saved.get('code')
    base = {'device_code': code, 'message': saved.get('message') or '', 'valid_until': None, 'days_left': None}
    if not address_book.mirrors(): return {**base, 'status': 'UNMANAGED'}   # no places listed (development, tests): the feature is off
    if 'serial' not in saved or (code and saved.get('code') and code != saved.get('code')): return {**base, 'status': 'UNMANAGED'}
    if not saved.get('listed'): return {**base, 'status': 'OVERDUE' if saved.get('strict') else 'UNMANAGED'}
    until = float(saved['valid_until']); left = until - now(saved, local)
    when = datetime.fromtimestamp(until, timezone.utc).isoformat().replace('+00:00', 'Z')
    status = 'OVERDUE' if left <= 0 else 'DUE_SOON' if left <= NOTICE_DAYS * 86400 else 'OK'
    return {**base, 'status': status, 'valid_until': when, 'days_left': max(0, int(left // 86400) + (1 if left % 86400 else 0)) if left > 0 else 0}


def due(saved=None):
    """Seconds until the next read of the file is due (0: now)."""
    saved = load() if saved is None else saved
    gap = BLOCKED_CHECK_SECONDS if state().get('status') == 'OVERDUE' else CHECK_SECONDS
    return max(0.0, float(saved.get('checked_at') or 0) + gap - time.time())


def refresh_in_background(machine_id_of):
    """Read the file in a thread when it is due; `machine_id_of` is called there (it asks the security core)."""
    if not address_book.mirrors() or due() > 0 or not _busy.acquire(blocking=False): return

    def run():
        try:
            machine = machine_id_of()
            if machine: refresh(machine)
        except Exception: pass
        finally: _busy.release()
    threading.Thread(target=run, daemon=True).start()
