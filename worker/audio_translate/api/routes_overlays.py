"""/api/overlays/*: the picture library and the templates that place logos and pictures on the video (video/overlays.py, docs/OVERLAYS.md).

Nothing here starts work or touches a run: a run copies the template it uses when it is created.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import Response

from audio_translate.api.routes_jobs import receive_upload
from audio_translate.api.web import json_response, local_request, threaded
from audio_translate.video import overlays

router = APIRouter()
LIMIT = overlays.MAX_BYTES


def _fail(error):
    status = 404 if error.code == 'OVERLAY_NOT_FOUND' else 409 if error.code in ('OVERLAY_IN_USE', 'OVERLAY_NAME_TAKEN') else 400
    return json_response({'error': error.code}, status)


async def _body(request: Request):
    if not request.headers.get('content-type', '').startswith('application/json'): return None, json_response({'error': 'JSON required'}, 415)
    text = (await request.body()).decode('utf-8', 'replace')
    if len(text) > 64 * 1024: return None, json_response({'error': 'Request too large'}, 400)
    try: value = json.loads(text)
    except ValueError: return None, json_response({'error': 'Invalid request'}, 400)
    return (value, None) if isinstance(value, dict) else (None, json_response({'error': 'Invalid request'}, 400))


@router.get('/api/overlays')
async def overview():
    return json_response(await threaded(overlays.listing), no_store=True)


@router.post('/api/overlays/assets')
async def add_asset(request: Request):
    """A picture, sent as the request body (the file name in ?name=). It becomes a PNG in the library."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    name = request.query_params.get('name') or ''
    if not name or len(name) > 255 or any(c in name for c in '\\/\x00'): return json_response({'error': 'OVERLAY_TYPE'}, 400)
    try: length = float(request.headers.get('content-length') or 0)
    except ValueError: length = 0
    if length > LIMIT: return json_response({'error': 'OVERLAY_TOO_BIG'}, 413)
    upload = None
    try:
        upload, refusal = await receive_upload(request, LIMIT)
        if refusal: return json_response({'error': 'OVERLAY_TOO_BIG'}, 413)
        return json_response({'asset': await threaded(overlays.import_asset, upload, name)}, 201, no_store=True)
    except overlays.OverlayError as error: return _fail(error)
    except Exception: return json_response({'error': 'OVERLAY_UNREADABLE'}, 400)
    finally:
        if upload: upload.unlink(missing_ok=True)


@router.get('/api/overlays/assets/{asset_id}')
async def get_asset(asset_id: str):
    try: path = overlays.asset_path(asset_id)
    except overlays.OverlayError as error: return _fail(error)
    if not path.is_file(): return json_response({'error': 'OVERLAY_NOT_FOUND'}, 404)
    return Response(await threaded(path.read_bytes), media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})


@router.delete('/api/overlays/assets/{asset_id}')
async def remove_asset(asset_id: str, request: Request):
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    try: await threaded(overlays.delete_asset, asset_id)
    except overlays.OverlayError as error: return _fail(error)
    return json_response({'deleted': True}, no_store=True)


@router.post('/api/overlays/templates')
async def save_template(request: Request):
    """Create a template, or replace one when the body carries its id."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    data, refusal = await _body(request)
    if refusal: return refusal
    try: template = await threaded(overlays.save_template, data)
    except overlays.OverlayError as error: return _fail(error)
    return json_response({'template': template}, 200 if data.get('id') else 201, no_store=True)


@router.delete('/api/overlays/templates/{template_id}')
async def remove_template(template_id: str, request: Request):
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    try: await threaded(overlays.delete_template, template_id)
    except overlays.OverlayError as error: return _fail(error)
    return json_response({'deleted': True}, no_store=True)


@router.put('/api/overlays/defaults')
async def put_default(request: Request):
    """{orientation, template}: the template every new video of that orientation uses (null clears it)."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    data, refusal = await _body(request)
    if refusal: return refusal
    template = data.get('template')
    if template is not None and not isinstance(template, str): return json_response({'error': 'OVERLAY_INVALID'}, 400)
    try: await threaded(overlays.set_default, data.get('orientation'), template)
    except overlays.OverlayError as error: return _fail(error)
    return json_response((await threaded(overlays.listing))['defaults'], no_store=True)


