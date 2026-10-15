"""Everything that starts or steers work, moved together with the scheduler (was app/api/jobs/**, app/api/tools/route.ts,
app/api/tools/[id]/review, app/api/quit and lib/server/app-control.ts)."""
import asyncio
import json
import os
import uuid

from fastapi import APIRouter, Request

from audio_translate.api import management
from audio_translate.api.history import ensure_history, history_list
from audio_translate.api.jobs import get_job, list_jobs, retry_job, scheduler, valid_youtube_url
from audio_translate.api.license import license_denial
from audio_translate.api.runtime import worker_command
from audio_translate.api.web import json_response, origin_allowed, threaded
from audio_translate.core.storage import DATA

router = APIRouter()
management.after_start.append(scheduler.soon)   # reprocess, resume and review start work: let the scheduler see it

VOICE_STYLES = ('default', 'drama', 'survival', 'rebirth')
ADDRESS_PROFILES = ('neutral', 'drama', 'survival', 'rebirth')
TRANSLATION_MODES = ('normal', 'genius')
TOOLS = ('transcription', 'translation', 'moderation', 'tts')
VIDEO_LIMIT = 64 * 1024   # the video settings (up to 50 paths) inside a request


def video_settings(value):
    """None (no videos), the settings dict, or False when they are malformed; the worker checks every clip itself."""
    if value is None: return None
    if isinstance(value, str):
        if len(value) > VIDEO_LIMIT: return False
        try: value = json.loads(value)
        except ValueError: return False
    return value if isinstance(value, dict) else False
GIB = 1024 ** 3


def command(payload):
    """manage.py with the keys JSON.stringify would keep (None means 'not given')."""
    return worker_command('manage.py', {k: v for k, v in payload.items() if v is not None})


async def receive_upload(request, limit):
    """Stream the body into data/uploads; returns (path, None) or (None, refusal). The caller deletes the file."""
    (DATA / 'uploads').mkdir(parents=True, exist_ok=True)
    path = DATA / 'uploads' / f'{uuid.uuid4()}.upload'
    received = 0
    with open(path, 'xb') as out:
        async for piece in request.stream():
            received += len(piece)
            if received > limit: return path, 'too large'
            out.write(piece)
        out.flush(); os.fsync(out.fileno())
    return path, None


# --- workflows -----------------------------------------------------------------------------------------------------------
@router.get('/api/jobs')
async def jobs():
    await threaded(scheduler.schedule)
    return json_response({'jobs': await threaded(list_jobs)}, no_store=True)


@router.post('/api/jobs')
async def create(request: Request):
    denied = await threaded(license_denial)
    if denied: return denied
    if not request.headers.get('content-type', '').startswith('application/json'): return await create_from_upload(request)
    try: data = json.loads(await request.body())
    except ValueError: return json_response({'error': 'JSON không hợp lệ.'}, 400)
    data = data if isinstance(data, dict) else {}
    url, voice, style, address, queue_only, mode, auto = (data.get(k) for k in ('url', 'voice', 'style', 'address', 'queue_only', 'mode', 'auto'))
    video = video_settings(data.get('video'))
    if video is False: return json_response({'error': 'Invalid video settings'}, 400)
    subtitle = video_settings(data.get('subtitle'))
    if subtitle is False: return json_response({'error': 'Invalid subtitle settings'}, 400)
    if 'auto' in data and not isinstance(auto, bool): return json_response({'error': 'Invalid auto option'}, 400)
    if not isinstance(url, str) or not valid_youtube_url(url): return json_response({'error': 'Hãy nhập URL video YouTube hợp lệ (HTTPS).'}, 400)
    if 'voice' in data and not isinstance(voice, str): return json_response({'error': 'Invalid voice'}, 400)
    if 'style' in data and style not in VOICE_STYLES: return json_response({'error': 'Invalid voice style'}, 400)
    if 'address' in data and address not in ADDRESS_PROFILES: return json_response({'error': 'Invalid address profile'}, 400)
    if 'queue_only' in data and not isinstance(queue_only, bool): return json_response({'error': 'Invalid queue option'}, 400)
    if 'mode' in data and mode not in TRANSLATION_MODES: return json_response({'error': 'Invalid translation mode'}, 400)
    try:
        await threaded(ensure_history)
        result = await threaded(command, {'action': 'convert', 'url': url, 'voice': voice, 'style': style, 'address': None if mode == 'genius' else address,
                                          'mode': mode, 'auto': auto is True, 'queue_only': queue_only or False, 'video': video, 'subtitle': subtitle})
    except Exception: return json_response({'error': 'Không kiểm tra được tài nguyên. Chưa tạo workflow; hãy thử lại.'}, 503)
    status = result.pop('status')
    if status == 200: scheduler.soon()
    return json_response(result, 201 if status == 200 else status, no_store=True)


async def create_from_upload(request: Request):
    """A workflow from a Chinese audio file instead of a YouTube link: same checks and queue; the worker validates the audio."""
    params = request.query_params
    name = params.get('name') or ''
    if not name or len(name) > 255 or any(c in name for c in '\\/\x00'): return json_response({'error': 'Tên file không hợp lệ.'}, 400)
    style = params.get('style') or None
    if style is not None and style not in VOICE_STYLES: return json_response({'error': 'Invalid voice style'}, 400)
    mode = params.get('mode') or None
    if mode is not None and mode not in TRANSLATION_MODES: return json_response({'error': 'Invalid translation mode'}, 400)
    address = None if mode == 'genius' else params.get('address') or None
    if address is not None and address not in ADDRESS_PROFILES: return json_response({'error': 'Invalid address profile'}, 400)
    if _length(request) > 2 * GIB: return json_response({'error': 'File quá lớn (tối đa 2 GB).'}, 413)
    video = video_settings(params.get('video'))
    if video is False: return json_response({'error': 'Invalid video settings'}, 400)
    subtitle = video_settings(params.get('subtitle'))
    if subtitle is False: return json_response({'error': 'Invalid subtitle settings'}, 400)
    upload = None
    try:
        upload, refusal = await receive_upload(request, 2 * GIB)
        if refusal: return json_response({'error': 'File quá lớn (tối đa 2 GB).'}, 413)
        await threaded(ensure_history)
        result = await threaded(command, {'action': 'convert', 'url': '', 'upload': str(upload), 'input_name': name, 'mime': request.headers.get('content-type', ''),
                                          'voice': params.get('voice') or None, 'style': style, 'address': address, 'mode': mode,
                                          'auto': params.get('auto') == '1', 'queue_only': params.get('queue_only') == '1', 'video': video, 'subtitle': subtitle})
        status = result.pop('status')
        if status == 200: scheduler.soon()
        return json_response(result, 201 if status == 200 else status, no_store=True)
    except Exception: return json_response({'error': 'Không nhận được file. Hãy kiểm tra file audio và dung lượng ổ đĩa.'}, 400)
    finally:
        if upload: upload.unlink(missing_ok=True)


def _length(request):
    try: return float(request.headers.get('content-length') or 0)
    except ValueError: return 0


@router.get('/api/jobs/preflight')
async def preflight():
    denied = await threaded(license_denial)
    if denied: return denied
    try: result = await threaded(worker_command, 'manage.py', {'action': 'preflight'})
    except Exception: return json_response({'error': 'Không kiểm tra được tài nguyên.'}, 503)
    status = result.pop('status')
    return json_response(result, status, no_store=True)


@router.get('/api/jobs/{job_id}')
async def job(job_id: str):
    await threaded(scheduler.schedule)
    found = await threaded(get_job, job_id)
    return json_response({'job': found}, no_store=True) if found else json_response({'error': 'Job không tồn tại.'}, 404)


@router.post('/api/jobs/{job_id}/retry')
async def retry(job_id: str):
    denied = await threaded(license_denial)
    if denied: return denied
    found = await threaded(retry_job, job_id)
    return json_response({'job': found}) if found else json_response({'error': 'Chỉ có thể retry job lỗi hoặc tiếp tục job chỉ có bản chép tiếng Trung.'}, 409)


async def step_command(job_id, step, action):
    if action == 'retry':
        denied = await threaded(license_denial)
        if denied: return denied
    try: result = await threaded(worker_command, 'retry.py', {'action': action, 'id': job_id, 'step': step, 'fresh': action == 'retry'})
    except Exception: return json_response({'error': 'Error service unavailable. Check PYTHON_BIN and .venv.'}, 503)
    status = result.pop('status')
    if status == 202: scheduler.soon()
    return json_response(result, status, no_store=True)


@router.get('/api/jobs/{job_id}/steps/{step}')
async def step_guide(job_id: str, step: str): return await step_command(job_id, step, 'guide')


@router.post('/api/jobs/{job_id}/steps/{step}')
async def step_retry(job_id: str, step: str): return await step_command(job_id, step, 'retry')


def _manage(action, scope='workflows'):
    async def handler(job_id: str, request: Request):
        return await threaded(management.management_response, (await request.body()).decode('utf-8', 'replace'), job_id, action, scope)
    return handler


for _action in ('abort', 'cancel', 'pause', 'reprocess', 'resume', 'review'):
    router.add_api_route(f'/api/jobs/{{job_id}}/{_action}', _manage(_action), methods=['POST'])
router.add_api_route('/api/tools/{job_id}/review', _manage('review', 'tools'), methods=['POST'])


# --- tools ---------------------------------------------------------------------------------------------------------------
@router.get('/api/tools')
async def tools(request: Request):
    await threaded(scheduler.schedule)
    return json_response(await threaded(history_list, dict(request.query_params), 'tools'))


@router.post('/api/tools')
async def create_tool(request: Request):
    denied = await threaded(license_denial)
    if denied: return denied
    if request.headers.get('content-type', '').startswith('application/json'):
        # Tool 1 from a YouTube link: queued like a workflow, stops after Transcription.
        try: data = json.loads(await request.body())
        except ValueError: return json_response({'error': 'Invalid JSON'}, 400)
        data = data if isinstance(data, dict) else {}
        if data.get('tool') == 'subtitle':
            # Tool 5: the subtitles (.srt) of a voice made by this app. Nothing is uploaded.
            subtitle = video_settings(data.get('subtitle'))
            if subtitle is False or not isinstance(data.get('voice_job'), str): return json_response({'error': 'Choose a voice'}, 400)
            result = await threaded(command, {'action': 'create', 'tool': 'subtitle', 'voice_job': data['voice_job'], 'subtitle': subtitle})
            status = result.pop('status')
            if status == 200: scheduler.soon()
            return json_response(result, 201 if status == 200 else status)
        if data.get('tool') == 'video':
            # Tool 6: a voice made by this app (a workflow or tool 4) laid over the chosen clips; with video.burn the subtitles are then drawn into a
            # second video (its `subtitle` settings apply). Nothing is uploaded.
            video, subtitle = video_settings(data.get('video')), video_settings(data.get('subtitle'))
            if not video or subtitle is False or not isinstance(data.get('voice_job'), str): return json_response({'error': 'Choose a voice and at least one video'}, 400)
            result = await threaded(command, {'action': 'create', 'tool': 'video', 'voice_job': data['voice_job'], 'video': video, 'subtitle': subtitle})
            status = result.pop('status')
            if status == 200: scheduler.soon()
            return json_response(result, 201 if status == 200 else status)
        if data.get('tool') != 'transcription' or not isinstance(data.get('url'), str) or not valid_youtube_url(data['url']):
            return json_response({'error': 'Enter a valid YouTube link'}, 400)
        result = await threaded(command, {'action': 'create', 'tool': data['tool'], 'url': data['url']})
        status = result.pop('status')
        if status == 200: scheduler.soon()
        return json_response(result, 201 if status == 200 else status)
    params = request.query_params
    tool, name = params.get('tool'), params.get('name') or ''
    if tool not in TOOLS or not name or len(name) > 255 or any(c in name for c in '\\/\x00'): return json_response({'error': 'Invalid tool or filename'}, 400)
    style = params.get('style') or None
    if style is not None and style not in VOICE_STYLES: return json_response({'error': 'Invalid voice style'}, 400)
    mode = params.get('mode') or None
    if mode is not None and (tool != 'translation' or mode not in TRANSLATION_MODES): return json_response({'error': 'Invalid translation mode'}, 400)
    address = None if mode == 'genius' else params.get('address') or None
    if address is not None and (tool != 'translation' or address not in ADDRESS_PROFILES): return json_response({'error': 'Invalid address profile'}, 400)
    limit = 2 * GIB if tool == 'transcription' else 64 * 1024 ** 2
    if _length(request) > limit: return json_response({'error': 'Upload too large'}, 413)
    upload = None
    try:
        upload, refusal = await receive_upload(request, limit)
        if refusal: return json_response({'error': 'Upload too large'}, 413)
        result = await threaded(command, {'action': 'create', 'tool': tool, 'upload': str(upload), 'input_name': name, 'mime': request.headers.get('content-type', ''),
                                          'voice': params.get('voice'), 'style': style, 'address': address, 'mode': mode,
                                          'auto': tool == 'tts' and params.get('auto') == '1'})
        status = result.pop('status')
        if status == 200: scheduler.soon()
        return json_response(result, 201 if status == 200 else status)
    except Exception: return json_response({'error': 'Cannot accept upload; check file and storage permissions.'}, 400)
    finally:
        if upload: upload.unlink(missing_ok=True)


# --- quit ----------------------------------------------------------------------------------------------------------------
def quit_info():
    """The installed app can quit: the desktop shell (AUDIO_SHELL) ends when the API exits with QUIT_EXIT_CODE.
    A development checkout has no shell, so there is nothing to quit and the answer says so."""
    return {'installed': bool(os.environ.get('AUDIO_SHELL')), 'active_jobs': scheduler.active_count()}


QUIT_EXIT_CODE = 75   # the shell (desktop/src/core.rs) treats this exit code as "the person chose Quit"; any other exit is a crash to restart


@router.get('/api/quit')
async def quit_status(): return json_response(quit_info(), no_store=True)


@router.post('/api/quit')
async def quit_app(request: Request):
    """Stops the installed app. With workflows running it needs {"force": true}; stopped ones resume at the next start."""
    if not origin_allowed(request): return json_response({'error': 'Origin rejected'}, 403)
    try: body = json.loads(await request.body())
    except ValueError: body = {}
    info = quit_info()
    force = isinstance(body, dict) and body.get('force') is True
    if not info['installed'] or (info['active_jobs'] > 0 and not force): return json_response({**info, 'stopped': False}, no_store=True)
    # After the answer has gone out, so the page that asked still receives it; the shell then ends the workers and closes the window.
    asyncio.get_running_loop().call_later(0.5, os._exit, QUIT_EXIT_CODE)
    return json_response({**info, 'stopped': True}, no_store=True)
