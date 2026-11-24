"""Where the server is: one small signed file on static hosting, read before the app asks the server for anything.

genius.json carries the address the app shipped with and `directory`: the places that each hold a copy of the same two files, `endpoint.json` and
`endpoint.json.sig` (for example GitHub Pages and Cloudflare Pages). The file says where the gateway and the Billing portal are now. When the owner
moves to another domain he signs a new file and publishes it; every app finds the new address by itself, with no new build and no overlap between
the old and the new domain.

The app never sends the licence to these places (a plain GET with nothing in it), and it trusts only a file signed by a key pinned in
endpoint-keys.json, so whoever controls a mirror, or buys an expired old domain, cannot send an app to a server of their own. A file older than the
one already saved is refused, so replaying an old copy changes nothing.

An app reads the file when it opens (at most once a day) and when a call to the server fails at network level (the name does not resolve, nothing
answers, the tunnel is down): then it asks once, at most every ten minutes, and sends the same call again if the server turned out to have moved.
"""
import base64
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from audio_translate.core.storage import DATA, ROOT, atomic_json

SCHEMA = 'audio-endpoint-v1'
STALE_SECONDS, FAILURE_GAP, FETCH_TIMEOUT, ASK_SECONDS, MAX_BYTES = 24 * 3600, 600, 5, 15, 16384
# Only these shapes are ever used as a server address: https and a host name (or the loopback for development), nothing after it.
ADDRESS = re.compile(r'https://([a-z0-9-]+\.)+[a-z0-9-]+(:\d{1,5})?|http://127\.0\.0\.1(:\d{1,5})?')
KEY_OF = {'endpoint': 'gateway', 'billing_url': 'billing'}   # genius.json's names for the two addresses -> the names inside the signed file
_lock, _throttle, _state = threading.Lock(), threading.Lock(), {'failure_at': -FAILURE_GAP, 'memo': None}


class EndpointError(ValueError):
    pass


def folder(): return DATA / 'endpoint'
def _config_path(): return ROOT / 'worker' / 'config' / 'genius.json'
def _keys_path(): return ROOT / 'worker' / 'config' / 'endpoint-keys.json'


def _config():
    try: value = json.loads(_config_path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}
    return value if isinstance(value, dict) else {}


def mirrors():
    """The places holding the signed file (genius.json `directory`). AUDIO_ENDPOINT_MIRRORS (comma-separated) replaces them: tests and development."""
    override = os.environ.get('AUDIO_ENDPOINT_MIRRORS')
    items = override.split(',') if override is not None else _config().get('directory', [])
    if not isinstance(items, list): return []
    return [i.strip().rstrip('/') for i in items if isinstance(i, str) and i.strip().startswith('https://')]


def public_keys():
    try: return [base64.b64decode(k) for k in json.loads(_keys_path().read_text(encoding='utf-8')).get('keys', [])]
    except (OSError, ValueError): return []


def verify(raw, signature, keys=None):
    """The file as a dict, only if one pinned key signed exactly these bytes and every field is in range."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES: raise EndpointError('size')
    try: sig = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError): raise EndpointError('signature encoding') from None
    for key in public_keys() if keys is None else keys:
        try: Ed25519PublicKey.from_public_bytes(key).verify(sig, raw); break
        except (InvalidSignature, ValueError): continue
    else: raise EndpointError('signature')
    try: data = json.loads(raw.decode('utf-8'))
    except ValueError: raise EndpointError('json') from None
    if not isinstance(data, dict) or data.get('schema') != SCHEMA: raise EndpointError('schema')
    if type(data.get('serial')) is not int or data['serial'] < 1: raise EndpointError('serial')
    for name in ('gateway', 'billing'):
        if not isinstance(data.get(name), str) or not ADDRESS.fullmatch(data[name]): raise EndpointError(name)
    return data


def current():
    """The saved file (verified again on every read, so a copied-in or edited file counts for nothing), or None."""
    path = folder() / 'directory.json'
    try: info = path.stat()
    except OSError: return None
    key = (str(path), info.st_mtime_ns, info.st_size)
    if _state['memo'] and _state['memo'][0] == key: return _state['memo'][1]
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        value = {**verify(saved['manifest'].encode('utf-8'), saved['signature']), 'fetched_at': float(saved.get('fetched_at') or 0)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError): value = None
    _state['memo'] = (key, value)
    return value


def cached(role):
    """'gateway' or 'billing' from the saved signed file, or None when there is none. With no places listed the feature is off, and a file saved earlier
    (by a development run, or before the list was emptied) overrides nothing."""
    if not mirrors(): return None
    value = current()
    return value[role] if value else None


def address(name):
    """The address for genius.json's `endpoint` / `billing_url`: the signed file's when the app has one, else the one it shipped with."""
    return cached(KEY_OF[name]) or _config().get(name)


def _get(url, opener=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'audio-translate-app/1', 'Cache-Control': 'no-cache'})
    with (opener or urllib.request.urlopen)(request, timeout=FETCH_TIMEOUT) as response: raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES: raise EndpointError('size')
    return raw


def refresh(opener=None, now=None):
    """Read the file from every place and keep the newest valid one (a stale copy never replaces a newer one). Safe to call from any thread."""
    with _lock:
        places = mirrors()
        if not places: return {'changed': False, 'serial': None, 'error': 'NO_DIRECTORY'}
        known = current(); best, error = None, 'UNREACHABLE'
        deadline = time.monotonic() + ASK_SECONDS
        for base in places:
            if best and time.monotonic() > deadline: break   # something was found and the rest are slow: do not hold the caller up
            try:
                raw, signature = _get(base + '/endpoint.json', opener), _get(base + '/endpoint.json.sig', opener).decode('ascii').strip()
                data = verify(raw, signature)
            except EndpointError as exc: error = f'FILE_{exc}'; continue
            except (OSError, ValueError, TimeoutError): continue   # this place is down; the others may answer
            if known and data['serial'] < known['serial']: error = 'OLDER_SERIAL'; continue
            if not best or data['serial'] > best[0]['serial']: best = (data, raw, signature)   # a place that lags behind another one is not the newest
        if not best: return {'changed': False, 'serial': known['serial'] if known else None, 'error': error}
        data, raw, signature = best
        atomic_json(folder() / 'directory.json', {'manifest': raw.decode('utf-8'), 'signature': signature, 'fetched_at': time.time() if now is None else now})
        return {'changed': not known or data['serial'] != known['serial'], 'serial': data['serial'], 'error': None}


def stale(now=None):
    value = current()
    return not value or (now or time.time()) - value['fetched_at'] > STALE_SECONDS


def refresh_in_background():
    """Called when the app opens: asks only when there is a place to ask and the saved file is more than a day old."""
    if mirrors() and stale(): threading.Thread(target=refresh, daemon=True).start()


def same_origin(a, b):
    x, y = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (x.scheme, x.netloc) == (y.scheme, y.netloc)


def swap_origin(url, base):
    """`url` with its scheme and host replaced by those of `base`."""
    parts, new = urllib.parse.urlsplit(url), urllib.parse.urlsplit(base)
    return urllib.parse.urlunsplit((new.scheme, new.netloc, parts.path, parts.query, parts.fragment))


def failover(failed, name='endpoint', opener=None, now=None):
    """A call to `failed` (the gateway's address, or the portal's with name='billing_url') failed at network level. Returns the address the server
    has now when it is another one, else None. The saved file is used if another call already found the move; otherwise the file is read,
    at most every ten minutes."""
    if not mirrors(): return None
    def moved():
        fresh = address(name)
        return fresh if fresh and not same_origin(fresh, failed) else None
    if moved(): return moved()
    moment = time.time() if now is None else now
    with _throttle:
        if moment - _state['failure_at'] < FAILURE_GAP: return None
        _state['failure_at'] = moment
    refresh(opener)
    return moved()
