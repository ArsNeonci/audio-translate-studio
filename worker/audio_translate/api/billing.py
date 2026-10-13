"""The Billing portal from the app (was lib/server/billing-portal.ts).

The portal is a page on the gateway where the customer pays service debt or buys a licence plan; plans, prices and wording
live on the server. This module only opens it (a one-time link made with the licence, or the remembered Customer Code when
the licence has expired) and installs the renewal tokens paid for there, so a paid renewal needs no copy and paste. The
native core releases the licence token only while the licence is valid.
"""
import json
import os
import re
import threading
import time
from urllib.parse import quote, urlsplit

from audio_translate.api import license as lease
from audio_translate.api.runtime import license_command
from audio_translate.core.storage import DATA

FILE = DATA / 'settings' / 'billing.json'
FAST_SECONDS, FAST_GAP, SLOW_GAP, CODE_REFRESH = 15 * 60, 4, 60, 24 * 3600
_state = {'fast_until': 0.0, 'at': 0.0, 'checked_code': 0.0}
_renewals = threading.Lock()


class BillingError(Exception):
    """An upper-case code the page shows, e.g. LICENSE_REVOKED, GATEWAY_UNREACHABLE, BILLING_CODE_UNKNOWN."""


def remembered():
    try:
        value = json.loads(FILE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError): return {}


def remember(code, portal_url):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = FILE.with_name(f'{FILE.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps({'code': code, 'portal_url': portal_url, 'saved_at': int(time.time() * 1000)}), encoding='utf-8')
    os.replace(temp, FILE)


def credential():
    reply = license_command({'action': 'credential'})
    return reply['token'] if reply.get('status') == 'ACTIVE' and isinstance(reply.get('token'), str) else None


def gateway(method, route, token, body=None):
    """(status, body) from the gateway, or None when it is not configured or cannot be reached."""
    base = lease.gateway_endpoint()
    return lease.gateway_call(method, f'{base}{route}', token, body) if base else None


def billing_info():
    """What the licence page shows: the Customer Code and whether the portal can be opened at all."""
    saved = remembered()
    stale = not saved.get('code') or time.time() * 1000 - (saved.get('saved_at') or 0) > CODE_REFRESH * 1000
    if stale and time.time() - _state['checked_code'] > 60:
        _state['checked_code'] = time.time()
        token = credential()
        reply = gateway('GET', '/v1/billing/code', token) if token else None
        if reply and reply[0] == 200 and isinstance(reply[1].get('code'), str) and isinstance(reply[1].get('portal_url'), str) and reply[1]['portal_url']:
            remember(reply[1]['code'], reply[1]['portal_url']); saved = remembered()
    info = {k: saved[k] for k in ('code', 'portal_url') if saved.get(k) is not None}
    info['enabled'] = bool(saved.get('code') and saved.get('portal_url')) or bool(lease.gateway_endpoint())
    return info


def open_billing(destination):
    """With a valid licence a one-time link that signs the customer in; without one the remembered Customer Code."""
    _state['fast_until'] = time.time() + FAST_SECONDS   # from now on look for the paid renewal every few seconds
    token = credential()
    if token:
        reply = gateway('POST', '/v1/billing/session', token, {'next': destination})
        if reply and reply[0] == 200 and isinstance(reply[1].get('url'), str):
            if isinstance(reply[1].get('customer_code'), str):
                parts = urlsplit(reply[1]['url'])
                try: remember(reply[1]['customer_code'], f'{parts.scheme}://{parts.netloc}')
                except OSError: pass
            return {'url': reply[1]['url'], 'mode': 'app'}
        if reply and reply[0] != 200 and reply[0] < 500: raise BillingError(str(reply[1].get('error') or f'HTTP_{reply[0]}'))
    saved = remembered()   # an expired licence, or the gateway could not be reached
    if saved.get('code') and saved.get('portal_url'):
        return {'url': f"{saved['portal_url']}/?code={quote(saved['code'], safe=chr(39) + '-_.!~*()')}", 'mode': 'code'}
    if not token:
        # No active licence and no remembered code: the portal's start page, where the customer types the Customer Code.
        home = lease.billing_url()
        if home: return {'url': f'{home}/', 'mode': 'home'}
    raise BillingError('GATEWAY_UNREACHABLE' if token else 'BILLING_CODE_UNKNOWN')


def fetch_renewals(force=False):
    """Install every renewal the gateway holds for this licence, in order. Concurrent callers wait for the one check; it asks
    every few seconds only for 15 minutes after the portal was opened, otherwise once a minute."""
    with _renewals:
        gap = FAST_GAP if time.time() < _state['fast_until'] else SLOW_GAP
        if not force and time.time() - _state['at'] < gap: return 0
        try: return _collect()
        except Exception: return 0
        finally: _state['at'] = time.time()


def _collect():
    token = credential()
    if not token: return 0   # an expired licence collects its token from the order page instead
    status = license_command({'action': 'status'})
    have = status['sequence'] if isinstance(status.get('sequence'), int) and not isinstance(status.get('sequence'), bool) else 0
    reply = gateway('GET', f'/v1/license/renewals?after={have}', token)
    items = reply[1]['renewals'] if reply and reply[0] == 200 and isinstance(reply[1].get('renewals'), list) else []
    installed = 0
    for item in sorted(items, key=lambda item: item.get('sequence') or 0 if isinstance(item, dict) else 0):
        if not isinstance(item, dict) or not isinstance(item.get('token'), str): break
        if license_command({'action': 'renew', 'token': item['token']}).get('status') != 'ACTIVE': break   # the next one would be out of order
        installed += 1
    if installed: lease.ensure_lease_in_background(True)   # a fresh licence gets its lease at once
    return installed


def error_code(error):
    code = str(error)
    return code if re.fullmatch(r'[A-Z_0-9]{3,60}', code) else 'BILLING_UNAVAILABLE'
