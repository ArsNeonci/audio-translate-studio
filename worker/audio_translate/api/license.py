"""The licence gate and the lease (was lib/server/license.ts licenseDenial and lib/server/lease.ts).

The lease is short-lived: the app asks the gateway for a new one while the licence is valid and the security service
verifies and stores it. It is renewed once half of it has passed, so an app opened now and then never lapses.
"""
import json
import threading
import time
import urllib.error
import urllib.request

from audio_translate.api.runtime import license_command
from audio_translate.api.web import json_response
from audio_translate.core.storage import ROOT

RECHECK_SECONDS, ERROR_RECHECK_SECONDS = 600, 60
_lock = threading.Lock()
_state = {'at': 0.0, 'last': None}


def _config_url(key):
    try: value = json.loads((ROOT / 'worker' / 'config' / 'genius.json').read_text(encoding='utf-8')).get(key)
    except (OSError, ValueError): return None
    return value.rstrip('/') if isinstance(value, str) and (value.startswith('https://') or value.startswith('http://127.0.0.1')) else None


def gateway_endpoint(): return _config_url('endpoint')


def billing_url():
    """The Billing portal's address; known without a licence, so an inactive app can still open its Customer Code page."""
    return _config_url('billing_url')


def app_version():
    try: value = json.loads((ROOT / 'licensing' / 'public-config.json').read_text(encoding='utf-8')).get('version')
    except (OSError, ValueError): return None
    import re
    return value if isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+', value) else None


def gateway_call(method, url, token, body=None, timeout=20):
    """(status, json body) from the gateway, or None when it cannot be reached."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={'Content-Type': 'application/json', 'Authorization': f'License {token}',
                                                                              'User-Agent': 'audio-translate-app/1'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response: status, raw = response.status, response.read()
    except urllib.error.HTTPError as error: status, raw = error.code, error.read()
    except (urllib.error.URLError, OSError, ValueError): return None
    try: value = json.loads(raw)
    except ValueError: value = {}
    return status, value if isinstance(value, dict) else {}


def _renew():
    status = license_command({'action': 'lease_status'})
    phase = status.get('lease') if isinstance(status.get('lease'), str) else 'UNKNOWN'
    if status.get('http_status') != 200 or status.get('renew') is not True: return {'lease': phase, 'renewed': False}
    base = gateway_endpoint()
    if not base: return {'lease': phase, 'renewed': False, 'error': 'GATEWAY_NOT_CONFIGURED'}
    credential, key = license_command({'action': 'credential'}), license_command({'action': 'machine_pubkey'})
    if credential.get('status') != 'ACTIVE' or not isinstance(credential.get('token'), str) or not isinstance(key.get('machine_pubkey'), str):
        return {'lease': phase, 'renewed': False, 'error': str(credential.get('status') or 'INVALID')}
    body = {'machine_public': key['machine_pubkey']}
    version = app_version()
    if version: body['app_version'] = version
    reply = gateway_call('POST', f'{base}/v1/lease', credential['token'], body)
    if reply is None: return {'lease': phase, 'renewed': False, 'error': 'GATEWAY_UNREACHABLE'}   # offline: the grace period covers this
    code, value = reply
    if code == 403 and value.get('error') == 'LICENSE_REVOKED':
        license_command({'action': 'lease_revoke'})   # stop new processing now, not at expiry
        return {'lease': 'REVOKED', 'renewed': False, 'error': 'LICENSE_REVOKED'}
    if not 200 <= code < 300 or not isinstance(value.get('lease'), str):
        return {'lease': phase, 'renewed': False, 'error': value.get('error') or f'HTTP_{code}'}
    installed = license_command({'action': 'install_lease', 'token': value['lease']})
    return {'lease': 'VALID', 'renewed': True} if installed.get('status') == 'OK' else {'lease': phase, 'renewed': False, 'error': str(installed.get('status') or 'INVALID')}


def ensure_lease(force=False):
    """Safe to call often: concurrent callers wait for the one check, and a fresh result is reused for ten minutes."""
    with _lock:
        last, age = _state['last'], time.monotonic() - _state['at']
        if not force and last and 'error' not in last and age < RECHECK_SECONDS: return last
        if not force and last and 'error' in last and age < ERROR_RECHECK_SECONDS: return last
        try: result = _renew()
        except Exception: result = {'lease': 'UNKNOWN', 'renewed': False, 'error': 'LEASE_CHECK_FAILED'}
        _state.update(last=result, at=time.monotonic())
        return result


def ensure_lease_in_background(force=False):
    threading.Thread(target=ensure_lease, args=(force,), daemon=True).start()


PERPETUAL_YEAR = 2100   # the admin's "Perpetual" is 36,500 days; any expiry from this year on is shown as perpetual and has nothing to renew


def perpetual(expires_at):
    try: return int(str(expires_at)[:4]) >= PERPETUAL_YEAR
    except ValueError: return False


def lease_phase():
    """VALID, GRACE, EXPIRED, NONE, REVOKED, or None when the service cannot say (development without the service)."""
    value = license_command({'action': 'lease_status'})
    phase = value.get('lease')
    return phase if value.get('http_status') == 200 and isinstance(phase, str) else None


def describe(result):
    """The licence status plus what the page needs: the lease phase and whether the licence never ends."""
    if result.get('status') != 'ACTIVE': return result
    return {**result, 'lease': lease_phase(), 'perpetual': perpetual(result.get('expires_at'))}


def license_denial(internet=True):
    """None when processing is allowed, else the 403 answer. Admission is when the lease matters, so it is refreshed first."""
    if internet: ensure_lease()
    result = license_command({'action': 'check', 'internet': internet})
    if result.get('status') == 'ACTIVE' and result.get('allowed') is True: return None
    error = result.get('error') or result.get('status')
    # The core says LICENSE_EXPIRED both for an expired licence and for a lease not renewed for too long (offline). When the licence itself is
    # still valid it is the lease: the person only has to go online, so they get that message instead of "licence expired".
    if error in ('LICENSE_EXPIRED', 'LEASE_REQUIRED') and license_command({'action': 'status'}).get('status') == 'ACTIVE': error = 'LEASE_OFFLINE'
    return json_response({'error': error, 'license_status': result.get('status')}, 403, no_store=True)
