"""/api/rules: replacement rules (was lib/server/rules.ts and app/api/rules/**)."""
import json

from fastapi import APIRouter, Request

from audio_translate.api.runtime import worker_command
from audio_translate.api.web import json_response, threaded

router = APIRouter()


async def respond(action, request=None, rule_id=None):
    try:
        payload = {}
        if request is not None and action != 'delete':
            text = (await request.body()).decode('utf-8', 'replace')
            if len(text) > 24000: return json_response({'error': 'Rule quá dài.'}, 400)
            try: payload = json.loads(text)
            except ValueError: return json_response({'error': 'JSON không hợp lệ.'}, 400)
            if not isinstance(payload, dict): return json_response({'error': 'JSON object required.'}, 400)
        command = {k: v for k, v in {'source': payload.get('source'), 'replacement': payload.get('replacement'), 'action': action, 'id': rule_id}.items() if v is not None}
        result = await threaded(worker_command, 'rules.py', command)
        status = result.pop('status')
        return json_response(result, status, no_store=True)
    except Exception:
        return json_response({'error': 'Không thể kết nối replacement rules service.'}, 500)


@router.get('/api/rules')
async def list_rules(): return await respond('list')


@router.post('/api/rules')
async def add_rule(request: Request): return await respond('add', request)


@router.put('/api/rules/{rule_id}')
async def edit_rule(rule_id: str, request: Request): return await respond('edit', request, rule_id)


@router.delete('/api/rules/{rule_id}')
async def delete_rule(rule_id: str, request: Request): return await respond('delete', request, rule_id)
