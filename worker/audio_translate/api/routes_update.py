"""/api/update/*: is there a newer release, download it, and install it (the app quits and updater.exe applies it). Local callers only."""
import asyncio
import json
import os

from fastapi import APIRouter, Request

from audio_translate.api import app_update
from audio_translate.api.routes_jobs import QUIT_EXIT_CODE, quit_info
from audio_translate.api.web import json_response, local_request, threaded

router = APIRouter()


@router.get('/api/update')
async def update_status():
    """The state of updates. Asking also starts a check in the background when one is due (opening the app is when the owner wants people to learn of a release)."""
    app_update.check_in_background()
    return json_response(await threaded(app_update.status), no_store=True)


@router.post('/api/update/check')
async def update_check(request: Request):
    """Check now (the Settings button). Returns the new state."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    await threaded(app_update.check, True)
    return json_response(await threaded(app_update.status), no_store=True)


@router.post('/api/update/download')
async def update_download(request: Request):
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    started = await threaded(app_update.start_download)
    return json_response({'started': started, **await threaded(app_update.status)}, no_store=True)


@router.post('/api/update/apply')
async def update_apply(request: Request):
    """Install the downloaded release: the app quits and updater.exe replaces it. With workflows running it needs {"force": true}; they continue after the update."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    try: body = json.loads(await request.body() or b'{}')
    except ValueError: body = {}
    force = isinstance(body, dict) and body.get('force') is True
    info = quit_info()
    if not info['installed'] or not app_update.install_root(): return json_response({'error': 'NOT_INSTALLED', **info}, 409, no_store=True)
    marker = await threaded(app_update.ready)
    if not marker: return json_response({'error': 'NOT_READY'}, 409, no_store=True)
    if info['active_jobs'] > 0 and not force: return json_response({'error': 'JOBS_RUNNING', **info}, 409, no_store=True)
    try: await threaded(app_update.write_plan, marker)
    except Exception as error: return json_response({'error': str(error) or 'PLAN_FAILED'}, 500, no_store=True)
    # After the answer has gone out; the shell sees the API end with the quit code, exits, and starts updater.exe (desktop/src/main.rs start_updater).
    asyncio.get_running_loop().call_later(0.7, os._exit, QUIT_EXIT_CODE)
    return json_response({'applying': True, 'version': marker['version'], 'kind': marker['kind']}, no_store=True)


@router.post('/api/update/ack')
async def update_ack(request: Request):
    """The person has seen how the last update ended."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    await threaded(app_update.acknowledge)
    return json_response({'ok': True}, no_store=True)
