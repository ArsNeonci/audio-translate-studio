"""/api/settings/compute and /api/settings/youtube (was app/api/settings/**). Local callers only."""
import json

from fastapi import APIRouter, Request

from audio_translate.api.runtime import worker_command
from audio_translate.api.web import json_response, local_request, threaded

router = APIRouter()


async def command(script, payload, unavailable):
    try:
        result = await threaded(worker_command, script, payload)
        status = result.pop('status')
        return json_response(result, status, no_store=True)
    except Exception:
        return json_response({'error': unavailable}, 503)


async def small_json(request: Request):
    """The JSON object of a settings change, or an error answer (415 not JSON, 400 too large or unreadable)."""
    if not request.headers.get('content-type', '').startswith('application/json'): return None, json_response({'error': 'JSON required'}, 415)
    text = (await request.body()).decode('utf-8', 'replace')
    if len(text) > 1024: return None, json_response({'error': 'Request too large'}, 400)
    try: return json.loads(text), None
    except ValueError: return None, json_response({'error': 'Invalid request'}, 400)


COMPUTE_UNAVAILABLE = 'Compute settings unavailable'
YOUTUBE_UNAVAILABLE = 'Không thể kết nối dịch vụ YouTube. Kiểm tra Python worker.'


@router.get('/api/settings/compute')
async def compute_status(request: Request):
    if not local_request(request): return json_response({'error': 'Local access required'}, 403)
    return await command('compute_settings.py', {'action': 'status'}, COMPUTE_UNAVAILABLE)


@router.post('/api/settings/compute')
async def compute_set(request: Request):
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    payload, refusal = await small_json(request)
    if refusal: return refusal
    if not isinstance(payload, dict) or payload.get('device') not in ('cpu', 'gpu'): return json_response({'error': 'Invalid compute device'}, 400)
    return await command('compute_settings.py', {'action': 'set', 'device': payload['device']}, COMPUTE_UNAVAILABLE)


@router.get('/api/settings/youtube')
async def youtube_status(request: Request):
    if not local_request(request): return json_response({'error': 'Local access required'}, 403)
    return await command('youtube_session.py', {'action': 'status'}, YOUTUBE_UNAVAILABLE)


@router.post('/api/settings/youtube')
async def youtube_action(request: Request):
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    payload, refusal = await small_json(request)
    if refusal: return refusal
    if not isinstance(payload, dict) or payload.get('action') not in ('open', 'check', 'disconnect', 'close_browser'):
        return json_response({'error': 'Invalid action'}, 400)
    return await command('youtube_session.py', {'action': payload['action']}, YOUTUBE_UNAVAILABLE)
