"""Request checks and JSON answers shared by the routers (the Python side of the old lib/server/origin.ts).

Origin checks compare against the Host header the caller used. The development proxy (scripts/dev.cjs) keeps that header
unchanged, so this works the same behind it and when the browser talks to this server directly.
"""
import hashlib
import hmac
import json
import os
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import Response

LOOPBACK = {'localhost', '127.0.0.1', '[::1]'}
TOKEN_HEADER = 'x-audio-api-token'
SESSION_COOKIE = 'audio_session'
NO_STORE = {'Cache-Control': 'no-store'}
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')


def api_token():
    token = os.environ.get('AUDIO_API_TOKEN', '')
    if len(token) < 32: raise SystemExit('AUDIO_API_TOKEN (32+ characters) is required')
    return token


def session_value(token):
    """What the browser's session cookie holds: derived from the launch token, so a new launch invalidates the old cookie."""
    return hmac.new(token.encode(), b'audio-session-v1', hashlib.sha256).hexdigest()


def authenticated_by(request: Request, token):
    """'header' (a caller that holds the token: the dev proxy, tests), 'cookie' (the browser after the launch link), or None."""
    if hmac.compare_digest(request.headers.get(TOKEN_HEADER, ''), token): return 'header'
    if hmac.compare_digest(request.cookies.get(SESSION_COOKIE, ''), session_value(token)): return 'cookie'
    return None


async def threaded(function, *args):
    """Run blocking work (a worker process, file reads) without holding up the event loop."""
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(function, *args)


def json_response(value, status=200, no_store=False, headers=None):
    """JSON as Next's Response.json wrote it: compact, UTF-8, application/json."""
    head = {**(NO_STORE if no_store else {}), **(headers or {})}
    return Response(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(), status, head, 'application/json')


def split_host(host):
    if host.startswith('['): name, _, rest = host.partition(']'); return name + ']', rest.lstrip(':')
    name, _, port = host.partition(':'); return name, port


def host_allowed(request: Request):
    """The Host header must be a loopback name: a page on another site that was re-pointed at 127.0.0.1 (DNS rebinding) is not."""
    return split_host(request.headers.get('host', ''))[0].lower() in LOOPBACK


def origin_allowed(request: Request):
    """No Origin (not a browser page), the server's own origin, or any loopback name with the same scheme and port."""
    header = request.headers.get('origin')
    if not header: return True
    try: origin = urlsplit(header)
    except ValueError: return False
    if not origin.scheme or not origin.hostname: return False
    host, scheme = request.headers.get('host', ''), request.url.scheme
    if f'{origin.scheme}://{origin.netloc}' == f'{scheme}://{host}': return True
    self_name, self_port = split_host(host)
    origin_name = '[' + origin.hostname + ']' if ':' in origin.hostname else origin.hostname
    origin_port = str(origin.port) if origin.port else ''
    return origin_name in LOOPBACK and self_name in LOOPBACK and origin.scheme == scheme and origin_port == self_port


def local_request(request: Request):
    """settings/*: a loopback address, an allowed origin, and no cross-site or same-site fetch."""
    return host_allowed(request) and origin_allowed(request) and request.headers.get('sec-fetch-site', '') not in ('cross-site', 'same-site')


def write_allowed(request: Request):
    """A request that changes something must come from this page itself: an allowed Origin and a fetch that is not cross-site or
    same-site (cookies are not isolated by port, so a page served on another local port is 'same-site' and must be refused)."""
    return origin_allowed(request) and request.headers.get('sec-fetch-site', '') not in ('cross-site', 'same-site')
