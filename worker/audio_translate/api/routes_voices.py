"""/api/voices and the pre-built voice samples (was app/api/voices/** and lib/server/voice-previews.ts)."""
import json
import re

from fastapi import APIRouter
from fastapi.responses import Response

from audio_translate.api.runtime import worker_command
from audio_translate.api.web import json_response, threaded
from audio_translate.core.storage import DATA, PUBLIC

router = APIRouter()
PREVIEWS = PUBLIC / 'voice-previews'
KEY = re.compile(r'^[a-f0-9]{64}$')


def voice_samples():
    """Samples listed in the manifest whose WAV file exists."""
    try: manifest = json.loads((PREVIEWS / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): manifest = {'voices': []}
    return [item for item in manifest.get('voices', []) if KEY.match(item.get('key', '')) and (PREVIEWS / f"{item['key']}.wav").is_file()]


def preview_builder_status():
    try: return json.loads((DATA / 'config' / 'voice-preview-builder.json').read_text(encoding='utf-8'))['status']
    except (OSError, ValueError, KeyError): return 'NOT_BUILT'


def voices():
    result = worker_command('manage.py', {'action': 'voices'})
    status = result.pop('status')
    samples = voice_samples()
    if isinstance(result.get('voices'), list):
        for voice in result['voices']:
            sample = next((item for item in samples if item.get('id') == voice.get('id')), None)
            voice['preview_url'] = f"/api/voices/preview/{sample['key']}" if sample else None
    return json_response({**result, 'preview_status': preview_builder_status()}, status, no_store=True)


@router.get('/api/voices')
async def list_voices(): return await threaded(voices)


@router.get('/api/voices/preview/{key}')
async def preview(key: str):
    if not KEY.match(key) or not any(item['key'] == key for item in await threaded(voice_samples)):
        return json_response({'error': 'Mẫu giọng chưa sẵn sàng'}, 404)
    try: data = await threaded((PREVIEWS / f'{key}.wav').read_bytes)
    except OSError: return json_response({'error': 'Không tìm thấy mẫu giọng'}, 404)
    return Response(data, 200, {'Cache-Control': 'public, max-age=31536000, immutable', 'X-Content-Type-Options': 'nosniff'}, 'audio/wav')
