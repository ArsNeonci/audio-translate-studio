"""/api/license, /api/billing and /api/model (was app/api/{license,billing,model}/route.ts)."""
import json
import threading

from fastapi import APIRouter, Request

from audio_translate.api import billing, license as lease, model
from audio_translate.api.runtime import edition, license_command
from audio_translate.api.web import json_response, origin_allowed, threaded

router = APIRouter()
ORIGIN_REJECTED = {'error': 'Origin rejected'}


@router.get('/api/license')
async def license_status(request: Request):
    lease.ensure_lease_in_background()                                   # opening the app renews the lease when it is due
    threading.Thread(target=billing.fetch_renewals, daemon=True).start()   # installs a renewal paid for in the Billing portal
    action = 'machine' if request.query_params.get('machine') == '1' else 'status'
    result = await threaded(license_command, {'action': action})
    if action == 'status': result = await threaded(lease.describe, result)
    tier = await threaded(edition)
    return json_response({**result, 'edition': tier}, result.get('http_status', 503), no_store=True)


@router.post('/api/license/lease')
async def license_lease_check(request: Request):
    """The "Check again" button: asks the gateway for a new lease now (the person has just gone online) and returns the new status."""
    if not origin_allowed(request): return json_response(ORIGIN_REJECTED, 403)
    renewal = await threaded(lease.ensure_lease, True)
    result = await threaded(lease.describe, await threaded(license_command, {'action': 'status'}))
    tier = await threaded(edition)
    return json_response({**result, 'edition': tier, 'renewal': renewal}, result.get('http_status', 503), no_store=True)


@router.post('/api/license')
async def license_change(request: Request):
    if not origin_allowed(request): return json_response(ORIGIN_REJECTED, 403)
    try:
        text = (await request.body()).decode('utf-8')
        if len(text) > 34000: return json_response({'error': 'Token quá dài.'}, 400)
        data = json.loads(text)
        if not isinstance(data, dict) or data.get('action') not in ('activate', 'renew') or not isinstance(data.get('token'), str):
            return json_response({'error': 'Invalid request'}, 400)
        result = await threaded(license_command, {'action': data['action'], 'token': data['token'].strip()})
    except (ValueError, UnicodeDecodeError): return json_response({'error': 'Invalid request'}, 400)
    if result.get('status') == 'ACTIVE': lease.ensure_lease_in_background(True)   # a fresh licence fetches its lease now
    return json_response(result, result.get('http_status', 503), no_store=True)


@router.get('/api/billing')
async def billing_info(): return json_response(await threaded(billing.billing_info), no_store=True)


@router.post('/api/billing')
async def billing_open(request: Request):
    """Returns the address to open in the browser; the customer never sees the licence token."""
    if not origin_allowed(request): return json_response(ORIGIN_REJECTED, 403)
    try:
        data = json.loads(await request.body())
        destination = 'debt' if isinstance(data, dict) and data.get('destination') == 'debt' else 'license'
        return json_response(await threaded(billing.open_billing, destination), no_store=True)
    except Exception as error:
        return json_response({'error': billing.error_code(error)}, 502, no_store=True)


@router.get('/api/model')
async def model_state(): return json_response(await threaded(model.model_state), no_store=True)


@router.post('/api/model')
async def model_start(request: Request):
    """Starts (or resumes) the download; the page polls GET."""
    if not origin_allowed(request): return json_response(ORIGIN_REJECTED, 403)
    return json_response(await threaded(model.start_model_download), no_store=True)
