"""/api/video/*: choosing the clips for Video merge, the size estimate, the voices tool 5 can use, and opening a finished video.

The clips stay where they are: the Windows dialog returns their paths, and the merge reads them in place.
"""
import json
import os
from pathlib import Path
import subprocess
import time

from fastapi import APIRouter, Request

from audio_translate.api.history import JOB_ID, ensure_history, job_dir, resolve_file
from audio_translate.api.runtime import worker_command
from audio_translate.api.web import json_response, local_request, threaded
from audio_translate.core.storage import DATA
from audio_translate.video import merge

router = APIRouter()
AUTO_OPEN_MINUTES = 10   # a video finished longer ago than this (the app was closed in between) is not opened by surprise


async def body_json(request: Request, limit=64 * 1024):
    if not request.headers.get('content-type', '').startswith('application/json'): return None, json_response({'error': 'JSON required'}, 415)
    text = (await request.body()).decode('utf-8', 'replace')
    if len(text) > limit: return None, json_response({'error': 'Request too large'}, 400)
    try: value = json.loads(text)
    except ValueError: return None, json_response({'error': 'Invalid request'}, 400)
    return (value, None) if isinstance(value, dict) else (None, json_response({'error': 'Invalid request'}, 400))


def check(paths):
    """Each clip as the merge sees it, or {path, name, error} for one that cannot be used."""
    out = []
    for path in paths:
        try: out.append(merge.probe(path))
        except merge.VideoError as error: out.append({'path': path, 'name': Path(path).name, 'error': error.code})
    return out


def pick():
    from audio_translate.api.dialog import choose_videos
    paths = choose_videos('Chọn video / Choose videos', merge.VIDEO_EXTENSIONS)
    if paths is None: return None
    return check(paths[:merge.MAX_FILES])


@router.post('/api/video/pick')
async def video_pick(request: Request):
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    try: files = await threaded(pick)
    except OSError: return json_response({'error': 'VIDEO_DIALOG_FAILED'}, 503)
    if files is None: return json_response({'error': 'VIDEO_DIALOG_OPEN'}, 409)
    return json_response({'files': files}, no_store=True)


@router.post('/api/video/check')
async def video_check(request: Request):
    """The chosen clips checked again (moved, deleted or changed since they were chosen)."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    data, refusal = await body_json(request)
    if refusal: return refusal
    paths = data.get('paths')
    if not isinstance(paths, list) or len(paths) > merge.MAX_FILES or any(not isinstance(p, str) or len(p) > 1024 for p in paths):
        return json_response({'error': 'Invalid paths'}, 400)
    return json_response({'files': await threaded(check, paths)}, no_store=True)


def voice_length(voice_job):
    path = merge.published_voice(voice_job) if voice_job else None
    if path is None:
        folder = job_dir(voice_job) if voice_job else None
        path = folder / 'voice.vi.wav' if folder and (folder / 'voice.vi.wav').is_file() else None
    return merge.voice_ms(path) if path else None


def estimate(paths, resolution, quality, voice_job):
    clips = check(paths)
    bad = [c for c in clips if c.get('error')]
    if bad: return {'files': clips, 'error': bad[0]['error']}
    allowed = merge.resolutions(clips)
    if resolution not in allowed: resolution = 'keep'
    length = voice_length(voice_job)
    plan = merge.plan(clips, resolution, quality, length)
    from audio_translate.workflow.results import RESULTS
    free = merge.disk_free(RESULTS)
    needed = merge.needed_bytes(plan) if length else None
    return {'files': clips, 'resolutions': allowed, 'resolution': resolution, 'quality': quality, 'plan': plan,
            'free_bytes': free, 'needed_bytes': needed, 'enough': None if needed is None else free >= needed}


@router.post('/api/video/estimate')
async def video_estimate(request: Request):
    """Expected size and the disk check. Without a voice yet (Studio) the size is per hour of voice."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    data, refusal = await body_json(request)
    if refusal: return refusal
    paths, resolution, quality, voice_job = data.get('paths'), data.get('resolution', 'keep'), data.get('quality', 'high'), data.get('voice_job')
    if (not isinstance(paths, list) or not 1 <= len(paths) <= merge.MAX_FILES or any(not isinstance(p, str) or len(p) > 1024 for p in paths)
            or resolution not in merge.RESOLUTIONS or quality not in merge.QUALITIES or (voice_job is not None and not JOB_ID.match(str(voice_job)))):
        return json_response({'error': 'Invalid request'}, 400)
    return json_response(await threaded(estimate, paths, resolution, quality, voice_job), no_store=True)


def voices():
    """Finished voices made by this app: workflows and tool 4 runs, newest first."""
    ensure_history()
    found = []
    for scope in ('workflows', 'tools'):
        result = worker_command('manage.py', {'action': 'history', 'scope': scope})
        for job in result.get('jobs') or []:
            if scope == 'tools' and job.get('tool_type') != 'tts': continue
            if not any(f.get('type') == 'VOICE_WAV' and f.get('status') == 'AVAILABLE' for f in job.get('files') or []): continue
            found.append({'job_id': job['id'], 'scope': scope, 'workflow_no': job.get('workflow_no'), 'name': job.get('name') or job.get('input_file') or '',
                          'created_at': job.get('created_at') or '', 'video': bool(job.get('video'))})
    found.sort(key=lambda item: item['created_at'], reverse=True)
    return found


@router.get('/api/video/voices')
async def video_voices():
    return json_response({'voices': await threaded(voices)}, no_store=True)


def video_file(job_id, scope):
    found = resolve_file(job_id, 'VIDEO_MP4', scope)
    return Path(found['file']) if found else None


def open_path(path, folder=False):
    if folder: subprocess.Popen(['explorer', '/select,', str(path)])
    else: os.startfile(str(path))   # the person's default video player


@router.post('/api/video/open')
async def video_open(request: Request):
    """Opens the finished video, or its folder with the file selected."""
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    data, refusal = await body_json(request, 1024)
    if refusal: return refusal
    job_id, scope, target = data.get('id'), data.get('scope', 'workflows'), data.get('target', 'video')
    if not JOB_ID.match(str(job_id or '')) or scope not in ('workflows', 'tools') or target not in ('video', 'folder'):
        return json_response({'error': 'Invalid request'}, 400)
    path = await threaded(video_file, job_id, scope)
    if not path or not path.is_file(): return json_response({'error': 'VIDEO_NOT_READY'}, 404)
    await threaded(open_path, path, target == 'folder')
    return json_response({'opened': True}, no_store=True)


def auto_open():
    """Videos finished while the app window is open are opened once. The page calls this every few seconds; the marker is
    removed before opening, so two windows never open the same video twice."""
    opened = []
    for root, scope in ((DATA / 'tmp', 'workflows'), (DATA / 'tool-tmp', 'tools')):
        if not root.is_dir(): continue
        for marker in root.glob('*/working/video-open.pending'):
            job_id = marker.parent.parent.name
            try: fresh = time.time() - marker.stat().st_mtime < AUTO_OPEN_MINUTES * 60
            except OSError: continue
            path = video_file(job_id, scope) if fresh and JOB_ID.match(job_id) else None
            if fresh and not (path and path.is_file()): continue      # not published yet: look again next time
            try: marker.unlink()
            except OSError: continue                                  # another caller took it
            if path: open_path(path); opened.append(job_id)
    return opened


@router.post('/api/video/auto-open')
async def video_auto_open(request: Request):
    if not local_request(request): return json_response({'error': 'Origin rejected'}, 403)
    return json_response({'opened': await threaded(auto_open)}, no_store=True)
