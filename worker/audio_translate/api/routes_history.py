"""Saved results: /api/history/**, /api/tools/{id} and its files, a job's artifacts, transcript, character sheet and errors
(was app/api/history/**, app/api/tools/[id]/**, app/api/jobs/[id]/{artifacts,transcript,characters,errors} and
lib/server/artifacts.ts). None of these starts work, so none needs the scheduler."""
import json
import os
import uuid

from fastapi import APIRouter, Request

from audio_translate.api.files import saved_file_response
from audio_translate.api.history import history_job, history_list, job_dir, resolve_file
from audio_translate.api.management import management_response, valid_character_sheet
from audio_translate.api.runtime import worker_command
from audio_translate.api.web import json_response, threaded

router = APIRouter()
KINDS = {'source': 'SOURCE', 'zh': 'ZH', 'vi': 'VI', 'moderated': 'MODERATED', 'voice': 'VOICE'}
EDITABLE = ('COMPLETED', 'FAILED', 'CANCELLED', 'PAUSED', 'PARTIAL')


@router.get('/api/history')
async def history(request: Request):
    try: return json_response(await threaded(history_list, dict(request.query_params)), no_store=True)
    except Exception: return json_response({'error': 'Không đọc được History. Kiểm tra cấu hình và quyền lưu kết quả.'}, 503)


@router.get('/api/history/{job_id}')
async def saved(job_id: str):
    try: job = await threaded(history_job, job_id)
    except Exception: return json_response({'error': 'Không đọc được History.'}, 503)
    return json_response({'job': job} if job else {'error': 'Job không tồn tại.'}, 200 if job else 404, no_store=True)


@router.delete('/api/history/{job_id}')
async def delete_saved(job_id: str, request: Request):
    return await threaded(management_response, (await request.body()).decode('utf-8', 'replace'), job_id, 'delete')


async def saved_file(request, job_id, file_id, download):
    try:
        found = await threaded(resolve_file, job_id, file_id)
        if not found: return json_response({'error': 'File không tồn tại.'}, 404)
        return await threaded(saved_file_response, request, found['file'], download)
    except Exception: return json_response({'error': 'Không đọc được file đã lưu.'}, 404)


@router.get('/api/history/{job_id}/files/{file_id}')
async def saved_file_inline(job_id: str, file_id: str, request: Request): return await saved_file(request, job_id, file_id, False)


@router.get('/api/history/{job_id}/files/{file_id}/download')
async def saved_file_download(job_id: str, file_id: str, request: Request): return await saved_file(request, job_id, file_id, True)


@router.get('/api/tools/{job_id}')
async def tool_run(job_id: str):
    job = await threaded(history_job, job_id, 'tools')
    return json_response({'job': job} if job else {'error': 'Tool run not found'}, 200 if job else 404)


@router.delete('/api/tools/{job_id}')
async def delete_tool_run(job_id: str, request: Request):
    return await threaded(management_response, (await request.body()).decode('utf-8', 'replace'), job_id, 'delete', 'tools')


@router.get('/api/tools/{job_id}/files/{file_id}')
async def tool_file(job_id: str, file_id: str, request: Request):
    found = await threaded(resolve_file, job_id, file_id, 'tools')
    if not found: return json_response({'error': 'Output unavailable or stale'}, 404)
    return await threaded(saved_file_response, request, found['file'], request.query_params.get('download') == '1')


async def artifact(request, job_id, kind):
    if kind not in KINDS: return json_response({'error': 'Unknown artifact'}, 404)
    params = request.query_params
    extension = 'WAV' if kind == 'voice' else 'AUDIO' if kind == 'source' else 'JSONL' if params.get('format') == 'jsonl' else 'MD'
    try:
        found = await threaded(resolve_file, job_id, f'{KINDS[kind]}_{extension}')
        if not found: return json_response({'error': 'Output chưa sẵn sàng.'}, 404)
        response = await threaded(saved_file_response, request, found['file'], params.get('download') == '1')
        # Studio's bounded plain-text preview.
        if params.get('preview') == '1' and kind not in ('voice', 'source') and 200 <= response.status_code < 300:
            data = json.loads(response.body)
            text = data['content'] + ('\n\n… Bản xem trước. Mở History để xem tiếp.' if data.get('next_offset') is not None else '')
            from fastapi.responses import Response
            return Response(text.encode(), 200, {'Cache-Control': 'no-store'}, 'text/plain; charset=utf-8')
        return response
    except Exception: return json_response({'error': 'Không đọc được output đã lưu.'}, 503)


@router.get('/api/jobs/{job_id}/artifacts/{kind}')
async def job_artifact(job_id: str, kind: str, request: Request): return await artifact(request, job_id, kind)


@router.get('/api/jobs/{job_id}/transcript')
async def job_transcript(job_id: str, request: Request): return await artifact(request, job_id, 'zh')


def locate(job_id):
    folder = job_dir(job_id)
    if not folder: return None
    try: job = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): return None
    return (folder, job, folder / 'working' / 'characters.json') if isinstance(job, dict) and job.get('storage_scope') != 'tools' else None


@router.get('/api/jobs/{job_id}/characters')
async def characters(job_id: str):
    found = await threaded(locate, job_id)
    if not found: return json_response({'error': 'Job không tồn tại.'}, 404)
    try: sheet = json.loads(found[2].read_text(encoding='utf-8'))
    except (OSError, ValueError): sheet = None
    return json_response({'sheet': valid_character_sheet(sheet), 'editable': found[1].get('status') in EDITABLE}, no_store=True)


@router.put('/api/jobs/{job_id}/characters')
async def save_characters(job_id: str, request: Request):
    found = await threaded(locate, job_id)
    if not found: return json_response({'error': 'Job không tồn tại.'}, 404)
    if found[1].get('status') not in EDITABLE: return json_response({'error': 'Pause or finish the current run first'}, 409)
    body = (await request.body()).decode('utf-8', 'replace')
    if len(body) > 256 * 1024: return json_response({'error': 'Request too large'}, 413)
    try: sheet = valid_character_sheet(json.loads(body))
    except ValueError: sheet = None
    if not sheet: return json_response({'error': 'Invalid character sheet'}, 400)
    target = found[2]
    temp = target.with_name(f'{target.name}.{uuid.uuid4()}.tmp')
    try:
        temp.write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding='utf-8'); os.replace(temp, target)
    finally: temp.unlink(missing_ok=True)
    return json_response({'sheet': sheet}, no_store=True)


@router.get('/api/jobs/{job_id}/errors')
async def errors(job_id: str):
    try:
        result = await threaded(worker_command, 'retry.py', {'action': 'errors', 'id': job_id})
        status = result.pop('status')
        return json_response(result, status, no_store=True)
    except Exception: return json_response({'error': 'Error service unavailable. Check PYTHON_BIN and .venv.'}, 503)
