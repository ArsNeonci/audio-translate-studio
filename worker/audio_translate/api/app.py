"""The FastAPI application: one router per group of /api routes, the built UI, and the checks in front of both.

Who may call /api:
  - the browser, after the launcher opened it with /?launch=<token>: that link is exchanged for an HttpOnly, SameSite=Strict
    session cookie and redirected to the same page without the token;
  - a caller that holds the token and sends it in X-Audio-Api-Token (the development proxy, the tests).
Everything else gets 403. Every request must name a loopback Host. A request that changes something must also come from this
page itself (see web.write_allowed).
"""
import hmac
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from audio_translate.api import routes_history, routes_jobs, routes_license, routes_rules, routes_settings, routes_voices, static
from audio_translate.api.web import SAFE_METHODS, SESSION_COOKIE, authenticated_by, host_allowed, json_response, session_value, write_allowed

# routes_jobs comes first: /api/jobs/preflight must win over /api/jobs/{job_id}.
ROUTERS = [routes_jobs.router, routes_rules.router, routes_voices.router, routes_settings.router, routes_history.router, routes_license.router]


def create_app(token, ui_dir=None):
    ui = Path(ui_dir) if ui_dir else None
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)   # publishes nothing of its own

    @app.middleware('http')
    async def guard(request: Request, call_next):
        if not host_allowed(request): return json_response({'error': 'Host rejected'}, 403, no_store=True)
        path = request.url.path
        if path.startswith('/api/') or path == '/api':
            via = authenticated_by(request, token)
            if not via: return json_response({'error': 'API token required'}, 403, no_store=True)
            if request.method not in SAFE_METHODS and via == 'cookie' and not write_allowed(request): return json_response({'error': 'Origin rejected'}, 403, no_store=True)
            return await call_next(request)
        if not ui: return json_response({'error': 'Not found'}, 404, no_store=True)
        launch = request.query_params.get('launch')
        if launch is not None:
            # The launcher's link: swap the one-time token for the session cookie and drop it from the address.
            if not hmac.compare_digest(launch, token): return static.locked_page()
            rest = {k: v for k, v in request.query_params.items() if k != 'launch'}
            response = RedirectResponse(path + ('?' + urlencode(rest) if rest else ''), 303)
            response.set_cookie(SESSION_COOKIE, session_value(token), httponly=True, samesite='strict', path='/')
            return response
        if request.method not in ('GET', 'HEAD'): return json_response({'error': 'Method not allowed'}, 405, no_store=True)
        # A page needs the session; assets do not (they are the same files for everyone).
        if static.is_page(path) and not authenticated_by(request, token): return static.locked_page()
        return static.serve(ui, path)

    for router in ROUTERS: app.include_router(router)
    return app
