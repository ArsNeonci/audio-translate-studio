"""Video merge (Ghép video): the Vietnamese voice made by this app laid over the person's own video clips.

The clips are read where they are (only their paths are kept) and never changed; their own sound is dropped. In the order they
were added they are played once, and the list is repeated (N = ceil(voice / clips)) until the voice ends, then cut exactly at the
end of the voice. A video longer than the voice is simply cut.

The cost is kept to the length of the clips, not of the voice:
  * clips that can be copied as they are (resolution "keep", one clip, or clips with the same codec, size and frame rate) are never
    re-encoded: one ffmpeg command loops and cuts them with `-c:v copy` (1 h of voice from a 37 s clip: 31 s, 52 MB RAM);
  * otherwise the clips are encoded once into one uniform base clip (black bars keep each picture whole, the chosen resolution and
    quality), and that base is then looped with `-c:v copy` the same way.
The voice is encoded to AAC 128 kbit/s. The result is an MP4 with the index at the front, so it plays while it is still loading.

Burning the Vietnamese subtitles into the picture is a separate step (BURN, `burn()` below, chosen by a tick) that runs after this merge, on
the finished video: it cannot copy the picture, so it encodes the whole length of the voice (measured 16 to 36 times slower than the copy), with
the .srt of video/subtitles.py drawn by libass. The plain video is always made first and kept; the subtitled one is a second file.

Ultra fast (the tick under the workflow's video settings, `video.ultra`) trades a little quality per bit for speed: x264 ultrafast instead of veryfast. With the subtitles
ticked as well it also folds BURN into this merge (no BURN step, one file: the subtitled video), see merge().
"""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from audio_translate.core.error_ids import AppError

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.mkv', '.webm', '.avi', '.wmv', '.flv', '.ts', '.mts', '.m2ts', '.3gp', '.mpg', '.mpeg'}
MAX_FILES = 50
RESOLUTIONS = ('keep', '1080', '720', '480')
QUALITIES = ('high', 'medium', 'light')
# Video bit rate in kbit/s per output height row and quality (Cao / Vừa / Nhẹ). The voice adds 128 kbit/s.
BITRATES = {1080: {'high': 8000, 'medium': 5000, 'light': 3000},
            720: {'high': 4000, 'medium': 2500, 'light': 1500},
            480: {'high': 2000, 'medium': 1200, 'light': 800}}
AUDIO_KBPS = 128
# Measured on the development PC (4 threads, libx264 veryfast, 30 fps): wall seconds per second of voice when the subtitles are burned in.
BURN_SECONDS_PER_SECOND = {1080: 0.3, 720: 0.13, 480: 0.07}
# Ultra fast (the tick under a workflow's video settings): x264 ultrafast, and with the subtitles ticked one encoding instead of two (merge() below). Measured on the
# development PC (8 threads, 1080p, 3 min of voice, logo + subtitles): 0.62 of the time of the same single encoding at veryfast (0.38 when a short clip is looped).
ULTRA_PRESET, NORMAL_PRESET = 'ultrafast', 'veryfast'
ULTRA_FACTOR = 0.6
def subtitle_style(width, height):
    """libass sizes are on a 288-line frame that is stretched to the picture's height. 14 gives about 5% of the height on a landscape picture;
    on a portrait one the same text size is taken from the short side, a little smaller, so a line does not fill the narrow width."""
    size = 14 * min(width, height) / height * (0.75 if height > width else 1)
    return f'FontName=Arial,FontSize={size:.1f},Outline=1.5,Shadow=0,MarginV=12,Alignment=2'
SUBTITLE_FILE = 'working/burn-sub.srt'
COPYABLE_CODECS = {'h264', 'hevc', 'av1', 'vp9', 'mpeg4'}
OUTPUT = 'video.vi.mp4'
BURN_OUTPUT = 'video.vi.sub.mp4'
BASE = 'working/video-base.mp4.tmp'
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


class VideoError(ValueError):
    """A problem the person can fix (a clip moved, deleted or unreadable, or too little disk space); `code` is shown translated."""
    def __init__(self, code, detail=''):
        super().__init__(f'{code}: {detail}' if detail else code)
        self.code, self.detail = code, detail


def _run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW, **kwargs)


def _fps(text):
    try:
        top, _, bottom = str(text).partition('/')
        value = float(top) / float(bottom or 1)
        return value if 0 < value < 1000 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe(path):
    """What the merge needs to know about one clip. Raises VideoError when it is not a readable video file."""
    path = Path(path)
    if not path.is_absolute(): raise VideoError('VIDEO_INVALID', path.name)
    if path.suffix.lower() not in VIDEO_EXTENSIONS: raise VideoError('VIDEO_TYPE', path.name)
    if not path.is_file(): raise VideoError('VIDEO_MISSING', path.name)
    result = _run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], timeout=60)
    try:
        info = json.loads(result.stdout or '{}')
    except ValueError:
        info = {}
    stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')), None)
    if result.returncode or not stream: raise VideoError('VIDEO_UNREADABLE', path.name)
    try: duration = float(stream.get('duration') or info.get('format', {}).get('duration') or 0)
    except ValueError: duration = 0
    width, height = int(stream.get('width') or 0), int(stream.get('height') or 0)
    if duration <= 0 or width <= 0 or height <= 0: raise VideoError('VIDEO_UNREADABLE', path.name)
    rotation = 0
    for side in stream.get('side_data_list') or []:
        if 'rotation' in side:
            try: rotation = int(float(side['rotation'])) % 360
            except ValueError: pass
    try: rotation = int(float((stream.get('tags') or {}).get('rotate', rotation))) % 360
    except ValueError: pass
    if rotation in (90, 270): width, height = height, width          # what the player shows
    stat = path.stat()
    try: bitrate = int(stream.get('bit_rate') or 0) or int(info.get('format', {}).get('bit_rate') or 0)
    except ValueError: bitrate = 0
    return {'path': str(path), 'name': path.name, 'size': stat.st_size, 'mtime': int(stat.st_mtime), 'duration_ms': int(duration * 1000),
            'width': width, 'height': height, 'fps': round(_fps(stream.get('avg_frame_rate')) or _fps(stream.get('r_frame_rate')) or 30, 3),
            'codec': stream.get('codec_name') or '', 'pix_fmt': stream.get('pix_fmt') or '', 'rotation': rotation,
            'bitrate': bitrate or int(stat.st_size * 8 / duration)}


def validate(config, current_overlay=None):
    """The video settings sent by the page, checked and with every clip probed again (the page's own numbers are never trusted).
    `overlay` is the choice of logo template ("default", "none" or a template id); the run keeps a snapshot of the template it names."""
    if not isinstance(config, dict): raise ValueError('Invalid video settings')
    files = config.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES: raise ValueError(f'Choose 1 to {MAX_FILES} videos')
    paths = [item.get('path') if isinstance(item, dict) else item for item in files]
    if any(not isinstance(p, str) or not p or len(p) > 1024 or '\x00' in p for p in paths): raise ValueError('Invalid video path')
    resolution = config.get('resolution', 'keep')
    quality = config.get('quality', 'high')
    if resolution not in RESOLUTIONS: raise ValueError('Invalid video resolution')
    if quality not in QUALITIES: raise ValueError('Invalid video quality')
    burn = config.get('burn', False)
    ultra = config.get('ultra', False)
    if not isinstance(burn, bool) or not isinstance(ultra, bool): raise ValueError('Invalid video settings')
    clips = [probe(p) for p in paths]
    allowed = resolutions(clips)
    if resolution not in allowed: raise ValueError('That resolution is higher than the videos')
    result = {'files': clips, 'resolution': resolution, 'quality': quality}
    if burn: result['burn'] = True   # the BURN step (subtitles drawn into a second video) follows this merge
    if ultra: result['ultra'] = True   # Ultra fast: x264 ultrafast; with burn, this merge draws the subtitles itself and the run has no BURN step
    from audio_translate.video import overlays
    try: snapshot = overlays.resolve(config.get('overlay'), clips, current_overlay)
    except overlays.OverlayError as error: raise VideoError(error.code)
    if snapshot: result['overlay'] = snapshot   # the logos and pictures laid on the picture (video/overlays.py); they force the encode
    return result


def resolutions(clips):
    """Keep, and every height that is not above the largest clip (a picture is never blown up)."""
    largest = max(min(c['width'], c['height']) for c in clips)
    return ['keep'] + [r for r in RESOLUTIONS[1:] if int(r) <= largest]


def _even(value): return max(2, int(round(value / 2)) * 2)


def plan(clips, resolution, quality, voice_ms, burn=False, overlay=False, ultra=False):
    """How the merge will run and how big the file will be (estimate)."""
    first = clips[0]
    same = all(c['codec'] == first['codec'] and c['width'] == first['width'] and c['height'] == first['height'] and abs(c['fps'] - first['fps']) < 0.01
               and c['pix_fmt'] == first['pix_fmt'] and c['rotation'] == first['rotation'] for c in clips)
    copy = resolution == 'keep' and same and first['codec'] in COPYABLE_CODECS and not burn and not overlay   # drawing text or a logo needs the picture re-encoded
    portrait = first['height'] > first['width']
    if resolution == 'keep':
        width, height = _even(first['width']), _even(first['height'])
    else:
        short = int(resolution)
        long_side = _even(short * (max(first['width'], first['height']) / min(first['width'], first['height'])))
        width, height = (short, long_side) if portrait else (long_side, short)
    row = min(BITRATES, key=lambda h: abs(h - min(width, height))) if resolution == 'keep' else int(resolution)
    fps = min(60.0, first['fps'] or 30.0)
    clips_ms = sum(c['duration_ms'] for c in clips)
    if copy:
        video_kbps = sum(c['bitrate'] * c['duration_ms'] for c in clips) / max(1, clips_ms) / 1000
    else:
        video_kbps = BITRATES[row][quality]
    size = int((video_kbps + AUDIO_KBPS) * 1000 / 8 * voice_ms / 1000 * 1.02) if voice_ms else None
    return {'mode': 'copy' if copy else 'encode', 'width': width, 'height': height, 'fps': round(fps, 3), 'video_kbps': int(video_kbps),
            'clips_ms': clips_ms, 'voice_ms': voice_ms, 'repeats': math.ceil(voice_ms / clips_ms) if voice_ms and clips_ms else None,
            'size_bytes': size, 'bytes_per_hour': int((video_kbps + AUDIO_KBPS) * 1000 / 8 * 3600 * 1.02), 'burn': burn,
            'seconds_per_voice_second': (BURN_SECONDS_PER_SECOND[row] * (ULTRA_FACTOR if ultra else 1) if burn else None), 'ultra': bool(ultra)}


def disk_free(path):
    path = Path(path)
    while not path.exists() and path != path.parent: path = path.parent
    return shutil.disk_usage(path).free


def needed_bytes(estimate):
    """The finished file, its copy while the index is moved to the front, and a margin."""
    return int(estimate['size_bytes'] * 2.1) + 512 * 1024 ** 2 if estimate['size_bytes'] else 0


def voice_ms(path):
    import soundfile as sf
    info = sf.info(str(path))
    return int(info.frames * 1000 / info.samplerate)


def voice_path(job_dir, job):
    """The voice to lay over the video: this run's own (workflow), or the published voice of the run tool 5 points at."""
    from audio_translate.workflow import results
    source = job.get('video_voice')
    if not source:
        own = Path(job_dir) / 'voice.vi.wav'
        if own.is_file(): return own
        source = {'job_id': job['id']}
    found = published_voice(source['job_id'])
    if not found: raise VideoError('VOICE_MISSING')
    return found


def published_voice(job_id):
    """The AVAILABLE published voice of a run (workflow or tool 4), or None."""
    return published_file(job_id, 'VOICE_WAV')


def published_file(job_id, kind):
    """The AVAILABLE published file of that type (VOICE_WAV, VIDEO_MP4, ...) of a run, or None."""
    from audio_translate.core.storage import read_json
    from audio_translate.workflow import results
    try:
        directory = results.destination(job_id)
        item = next((f for f in read_json(directory / 'outputs.json')['files'] if f.get('type') == kind and f.get('status') == 'AVAILABLE'), None)
    except (OSError, ValueError, KeyError):
        return None
    if not item: return None
    path = (directory / item['path']).resolve()
    return path if path.is_file() and path.is_relative_to(directory.resolve()) else None


def _filters(clips, width, height, fps, pictures=(), subtitle=None):
    """The clips joined into one picture; `pictures` [(x, y, size, opacity)] are laid on it in order, the inputs following the clips."""
    parts = []
    for index, _ in enumerate(clips):
        parts.append(f'[{index}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,'
                     f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p[v{index}]')
    joined = ''.join(f'[v{i}]' for i in range(len(clips)))
    last = 'pre' if subtitle else 'out'     # `subtitle` (a libass filter) is drawn last, on the finished picture
    if not pictures:
        parts.append(f'{joined}concat=n={len(clips)}:v=1:a=0[{last}]')
        if subtitle: parts.append(f'[pre]{subtitle}[out]')
        return ';'.join(parts)
    parts.append(f'{joined}concat=n={len(clips)}:v=1:a=0[cat]')
    previous = 'cat'
    for index, (x, y, size, opacity) in enumerate(pictures):
        source = len(clips) + index
        mix = f',colorchannelmixer=aa={opacity:.3f}' if opacity < 1 else ''
        # A still picture is one frame; the overlay repeats it for as long as the video runs (eof_action=repeat is the default).
        parts.append(f'[{source}:v]scale={size}:-2,format=rgba{mix}[p{index}]')
        parts.append(f'[{previous}][p{index}]overlay={x}:{y}:format=auto[o{index}]')
        previous = f'o{index}'
    parts.append(f'[{previous}]format=yuv420p[{last}]')
    if subtitle: parts.append(f'[pre]{subtitle}[out]')
    return ';'.join(parts)


def _ffmpeg(args, job_dir, total_ms, report, cwd=None, error_id='H104'):
    """Runs ffmpeg with progress on stdout; stops it at once when the run is cancelled or paused."""
    from audio_translate.core.control import Cancelled, check_cancel
    process = subprocess.Popen(['ffmpeg', '-hide_banner', '-nostdin', '-y', '-progress', 'pipe:1', '-nostats', *args], cwd=cwd,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    errors = []
    import threading
    reader = threading.Thread(target=lambda: errors.extend(process.stderr.read().splitlines()[-20:]), daemon=True)
    reader.start()
    last = 0.0
    try:
        for line in process.stdout:
            key, _, value = line.strip().partition('=')
            if key == 'out_time_us' and value.isdigit() and total_ms:
                if time.monotonic() - last > 1:
                    last = time.monotonic()
                    try: check_cancel(job_dir)
                    except Cancelled:
                        process.kill(); raise
                    report(min(1.0, int(value) / 1000 / total_ms))
        process.wait()
    finally:
        if process.poll() is None: process.kill(); process.wait()
        reader.join(5)
        process.stdout.close(); process.stderr.close()
    check_cancel(job_dir)
    if process.returncode:
        raise AppError(error_id, 'ffmpeg failed: ' + ' | '.join(errors[-3:]))


def _x264(preset, kbps, fps, threads):
    """The libx264 arguments of every picture encoding of the merge: the bit rate of the chosen quality, a key frame every 2 seconds."""
    return ['-c:v', 'libx264', '-preset', preset, '-b:v', f'{kbps}k', '-maxrate', f'{int(kbps * 1.5)}k', '-bufsize', f'{kbps * 2}k',
            '-g', str(int(round(fps * 2))), '-pix_fmt', 'yuv420p', '-threads', threads]


def _subtitle_filter(subtitle_file, width, height):
    # ffmpeg runs in the .srt's folder, so the filter names it without a drive letter (a colon would end the filter's argument).
    return f"subtitles={subtitle_file.name}:force_style='{subtitle_style(width, height)}'"


def _write_subtitles(job_dir, job):
    """The .srt of this voice (its own run, or the run the tool points at), with the subtitle settings of this run, written for drawing."""
    from audio_translate.video import subtitles
    subtitle_file = Path(job_dir) / SUBTITLE_FILE
    manifest, wav_dir, total = subtitles.voice_inputs(job_dir, job)
    subtitles.write(subtitle_file, manifest, wav_dir, subtitles.validate(job.get('subtitle')), total)
    return subtitle_file


def merge(job_dir):
    """The VIDEO stage of a run: the voice over the clips, picture copied whenever it can be (the BURN stage, if chosen, comes after).

    Ultra fast (job.video.ultra): every picture encoding here is x264 ultrafast. With the subtitles ticked as well, the run has no BURN stage: this stage
    makes the subtitled video (video.vi.sub.mp4) by itself, encoding the whole length once instead of twice. When the clips are shorter than the voice, the
    logo is drawn on the short clip once and ONE encoding then loops it, adds the voice and draws the subtitles (drawing the logo again on every loop is
    slower); when they cover the voice, one ffmpeg command does the clips, the logo, the voice and the subtitles."""
    from audio_translate.core.storage import progress, read_json, update_job
    job_dir = Path(job_dir).resolve()
    job = read_json(job_dir / 'job.json')
    config = job.get('video') or {}
    ultra = bool(config.get('ultra'))
    burning = ultra and bool(config.get('burn'))
    preset = ULTRA_PRESET if ultra else NORMAL_PRESET
    voice = voice_path(job_dir, job)
    length = voice_ms(voice)
    if length <= 0: raise VideoError('VOICE_MISSING')
    # The clips are checked again now: they may have been moved, deleted or changed since they were chosen.
    clips = []
    for item in config.get('files') or []:
        clips.append(probe(item['path']))
    if not clips: raise VideoError('VIDEO_MISSING')
    snapshot = config.get('overlay')
    estimate = plan(clips, config.get('resolution', 'keep'), config.get('quality', 'high'), length, overlay=bool(snapshot))
    # The subtitled video is always encoded (never copied), at the bit rate of the chosen quality.
    final = plan(clips, config.get('resolution', 'keep'), config.get('quality', 'high'), length, burn=True, overlay=bool(snapshot), ultra=True) if burning else estimate
    pictures, inputs_after = [], []
    if snapshot:
        from audio_translate.video import overlays
        for asset, x, y, size, opacity in overlays.pixel_items(snapshot, estimate['width'], estimate['height']):
            found = overlays.picture(job_dir, asset)
            if not found: raise VideoError('OVERLAY_MISSING')
            pictures.append((x, y, size, opacity)); inputs_after += ['-i', str(found)]
    from audio_translate.workflow import results
    target_dir = results.destination(job['id'])
    if disk_free(target_dir) < needed_bytes(final) or disk_free(job_dir) < needed_bytes(final):
        raise OSError(28, f'No space left on device: the video needs about {needed_bytes(final) // 1024 ** 2} MB')
    update_job(job_dir, video={**config, 'files': clips}, video_plan=final)
    share = 0.0
    def report(phase_from, phase_to):
        return lambda fraction: progress(job_dir, 'video', 'VIDEO_MERGING', round((phase_from + (phase_to - phase_from) * fraction) * 1000), 1000)
    progress(job_dir, 'video', 'VIDEO_MERGING', 0, 1000)
    threads = str(max(1, (os.cpu_count() or 2) // 2))          # leave half the processor to the rest of the PC and other runs
    base = job_dir / BASE
    out_name = BURN_OUTPUT if burning else OUTPUT
    temp = job_dir / (out_name + '.tmp')
    sound = ['-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k']
    end = ['-t', f'{length / 1000:.3f}', '-movflags', '+faststart', '-f', 'mp4', str(temp)]
    subtitle_file = None
    try:
        if burning: subtitle_file = _write_subtitles(job_dir, job)
        if burning and estimate['mode'] == 'encode' and estimate['clips_ms'] >= length:
            # The clips cover the whole voice, so there is nothing to loop: one encoding does everything. The voice is the input after the pictures.
            graph = _filters(clips, estimate['width'], estimate['height'], estimate['fps'], pictures, _subtitle_filter(subtitle_file, estimate['width'], estimate['height']))
            inputs = [arg for c in clips for arg in ('-i', c['path'])] + inputs_after + ['-i', str(voice)]
            _ffmpeg([*inputs, '-filter_complex', graph, '-map', '[out]', '-map', f'{len(clips) + len(pictures)}:a:0', *_x264(preset, final['video_kbps'], final['fps'], threads), *sound, *end],
                    job_dir, length, report(0, 1.0), cwd=str(subtitle_file.parent))
        else:
            if estimate['mode'] == 'copy' and len(clips) == 1:
                source = clips[0]['path']
                share = 0.02 if burning else 0.0
            elif estimate['mode'] == 'copy':
                # Identical clips: joined without re-encoding.
                listing = job_dir / 'working' / 'video-list.txt.tmp'
                listing.write_text(''.join("file '" + c['path'].replace("'", "'\\''") + "'\n" for c in clips), encoding='utf-8')
                share = 0.1
                _ffmpeg(['-f', 'concat', '-safe', '0', '-i', str(listing), '-map', '0:v:0', '-c:v', 'copy', '-an', '-f', 'mp4', str(base)],
                        job_dir, estimate['clips_ms'], report(0, share))
                source = str(base)
            else:
                # Different clips, or another resolution or quality: encode them once, only as much as the voice needs.
                # With the subtitles ticked (ultra) the second encoding is the heavy one, so this one is a smaller part of the progress.
                base_ms = min(estimate['clips_ms'], length)
                share = base_ms / (base_ms + length) if burning else min(0.8, max(0.3, estimate['clips_ms'] / (estimate['clips_ms'] + length / 8)))
                inputs = [arg for c in clips for arg in ('-i', c['path'])] + inputs_after
                _ffmpeg([*inputs, '-filter_complex', _filters(clips, estimate['width'], estimate['height'], estimate['fps'], pictures), '-map', '[out]', '-an',
                         '-t', f'{length / 1000:.3f}', *_x264(preset, estimate['video_kbps'], estimate['fps'], threads), '-f', 'mp4', str(base)],
                        job_dir, base_ms, report(0, share))
                source = str(base)
            if burning:
                # The one encoding of the whole length: the short picture looped, the voice, the subtitles.
                _ffmpeg(['-stream_loop', '-1', '-i', source, '-i', str(voice), '-map', '0:v:0', '-map', '1:a:0',
                         '-vf', _subtitle_filter(subtitle_file, final['width'], final['height']), *_x264(preset, final['video_kbps'], final['fps'], threads), *sound, *end],
                        job_dir, length, report(share, 1.0), cwd=str(subtitle_file.parent))
            else:
                _ffmpeg(['-stream_loop', '-1', '-i', source, '-i', str(voice), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', *sound, *end],
                        job_dir, length, report(share, 1.0))
        os.replace(temp, job_dir / out_name)
    finally:
        temp.unlink(missing_ok=True); base.unlink(missing_ok=True)
        (job_dir / 'working' / 'video-list.txt.tmp').unlink(missing_ok=True)
        if subtitle_file: subtitle_file.unlink(missing_ok=True)
    progress(job_dir, 'video', 'VIDEO_MERGING', 1000, 1000)


def burn(job_dir):
    """The BURN stage: the subtitles drawn into a second copy of the finished video (video.vi.sub.mp4). The plain video is read where it was
    published and is not touched; the sound is copied, only the picture is encoded (libx264), the whole length of the voice."""
    from audio_translate.core.storage import progress, read_json, update_job
    job_dir = Path(job_dir)
    job = read_json(job_dir / 'job.json')
    source = published_file(job['id'], 'VIDEO_MP4')
    if not source: raise VideoError('VIDEO_RESULT_MISSING')
    clip = probe(source)
    length = clip['duration_ms']
    fast = bool(job.get('burn_ultra'))   # the Reprocess tick on this stage: the fastest encoder setting for this drawing
    estimate = plan([clip], 'keep', (job.get('video') or {}).get('quality', 'high'), length, True, ultra=fast)
    from audio_translate.workflow import results
    target_dir = results.destination(job['id'])
    if disk_free(target_dir) < needed_bytes(estimate) or disk_free(job_dir) < needed_bytes(estimate):
        raise OSError(28, f'No space left on device: the subtitled video needs about {needed_bytes(estimate) // 1024 ** 2} MB')
    update_job(job_dir, burn_plan=estimate)
    # The .srt of this voice (its own run, or the run the tool points at), with the subtitle settings of this run.
    subtitle_file = _write_subtitles(job_dir, job)
    progress(job_dir, 'burn', 'VIDEO_BURNING', 0, 1000)
    threads = str(max(1, (os.cpu_count() or 2) // 2))
    kbps = estimate['video_kbps']
    temp = job_dir / (BURN_OUTPUT + '.tmp')
    try:
        # ffmpeg runs in the working folder, so the filter names the .srt without a drive letter (a colon would end the filter's argument).
        _ffmpeg(['-i', str(source), '-map', '0:v:0', '-map', '0:a:0', '-vf', f"subtitles={subtitle_file.name}:force_style='{subtitle_style(estimate['width'], estimate['height'])}'",
                 '-c:v', 'libx264', '-preset', ULTRA_PRESET if fast else NORMAL_PRESET, '-b:v', f'{kbps}k', '-maxrate', f'{int(kbps * 1.5)}k', '-bufsize', f'{kbps * 2}k',
                 '-g', str(int(round(estimate['fps'] * 2))), '-pix_fmt', 'yuv420p', '-threads', threads, '-c:a', 'copy', '-movflags', '+faststart', '-f', 'mp4', str(temp)],
                job_dir, length, lambda fraction: progress(job_dir, 'burn', 'VIDEO_BURNING', round(fraction * 1000), 1000), cwd=str(subtitle_file.parent), error_id='H105')
        os.replace(temp, job_dir / BURN_OUTPUT)
    finally:
        temp.unlink(missing_ok=True)
        subtitle_file.unlink(missing_ok=True)
    progress(job_dir, 'burn', 'VIDEO_BURNING', 1000, 1000)


RENDER_OUTPUT = 'video.render.mp4'
RENDER_SUBTITLE = 'working/render.srt'
MP4_AUDIO = {'aac', 'mp3', 'ac3', 'eac3', 'alac', 'mp2'}     # sound that can be copied into an MP4; anything else is encoded to AAC


def audio_codec(path):
    """The codec of the first sound stream of a file, or None when it has no sound."""
    result = _run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', str(path)], timeout=60)
    return (result.stdout or '').strip().splitlines()[0] if result.returncode == 0 and (result.stdout or '').strip() else None


def render_plan(clip, resolution, quality, subtitle, overlay):
    """What tools 8 (subtitles) and 9 (logo) will do to one video and what it costs: the whole picture is encoded once, so the time follows the
    length of the video (the figures are the ones measured for the BURN step)."""
    plan_ = plan([clip], resolution, quality, clip['duration_ms'], burn=bool(subtitle), overlay=bool(overlay))
    row = min(BURN_SECONDS_PER_SECOND, key=lambda h: abs(h - min(plan_['width'], plan_['height'])))
    plan_['seconds_per_second'] = BURN_SECONDS_PER_SECOND[row]
    plan_['seconds'] = round(clip['duration_ms'] / 1000 * BURN_SECONDS_PER_SECOND[row])
    return plan_


def render(job_dir):
    """The RENDER stage of tools 8 (the person's subtitle file drawn into the picture) and 9 (the logo template laid on it), in one encoding pass.
    The video is read where it is; its own sound is kept (copied when an MP4 can hold it)."""
    from audio_translate.core.storage import progress, read_json, update_job
    job_dir = Path(job_dir)
    job = read_json(job_dir / 'job.json')
    config = job.get('render') or {}
    clip = probe((config.get('video') or {}).get('path', ''))
    length = clip['duration_ms']
    subtitle = job_dir / RENDER_SUBTITLE
    wants_subtitle = bool(config.get('subtitle'))
    if wants_subtitle and not subtitle.is_file(): raise VideoError('SUBTITLE_FILE_MISSING')
    snapshot = config.get('overlay')
    if not wants_subtitle and not snapshot: raise VideoError('RENDER_NOTHING')
    estimate = render_plan(clip, config.get('resolution', 'keep'), config.get('quality', 'high'), wants_subtitle, snapshot)
    from audio_translate.workflow import results
    target_dir = results.destination(job['id'])
    if disk_free(target_dir) < needed_bytes(estimate) or disk_free(job_dir) < needed_bytes(estimate):
        raise OSError(28, f'No space left on device: the video needs about {needed_bytes(estimate) // 1024 ** 2} MB')
    update_job(job_dir, render={**config, 'video': clip}, video_plan=estimate)
    width, height = estimate['width'], estimate['height']
    pictures, inputs_after = [], []
    if snapshot:
        from audio_translate.video import overlays
        for asset, x, y, size, opacity in overlays.pixel_items(snapshot, width, height):
            found = overlays.picture(job_dir, asset)
            if not found: raise VideoError('OVERLAY_MISSING')
            pictures.append((x, y, size, opacity)); inputs_after += ['-i', str(found)]
    parts = [f'[0:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p[b0]']
    previous = 'b0'
    for index, (x, y, size, opacity) in enumerate(pictures):
        mix = f',colorchannelmixer=aa={opacity:.3f}' if opacity < 1 else ''
        parts.append(f'[{1 + index}:v]scale={size}:-2,format=rgba{mix}[p{index}]')
        parts.append(f'[{previous}][p{index}]overlay={x}:{y}:format=auto[b{index + 1}]')
        previous = f'b{index + 1}'
    if wants_subtitle:
        # ffmpeg runs in the working folder, so the filter names the .srt without a drive letter (a colon would end the filter's argument).
        parts.append(f"[{previous}]subtitles={subtitle.name}:force_style='{subtitle_style(width, height)}'[out]")
    else:
        parts.append(f'[{previous}]null[out]')
    codec = audio_codec(clip['path'])
    sound = [] if codec is None else ['-map', '0:a:0', '-c:a', 'copy'] if codec in MP4_AUDIO else ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '192k']
    threads = str(max(1, (os.cpu_count() or 2) // 2))
    kbps = estimate['video_kbps']
    temp = job_dir / (RENDER_OUTPUT + '.tmp')
    progress(job_dir, 'render', 'VIDEO_RENDERING', 0, 1000)
    try:
        _ffmpeg(['-i', clip['path'], *inputs_after, '-filter_complex', ';'.join(parts), '-map', '[out]', *sound, '-c:v', 'libx264', '-preset', 'veryfast',
                 '-b:v', f'{kbps}k', '-maxrate', f'{int(kbps * 1.5)}k', '-bufsize', f'{kbps * 2}k', '-g', str(int(round(estimate['fps'] * 2))), '-pix_fmt', 'yuv420p',
                 '-threads', threads, '-movflags', '+faststart', '-f', 'mp4', str(temp)],
                job_dir, length, lambda fraction: progress(job_dir, 'render', 'VIDEO_RENDERING', round(fraction * 1000), 1000), cwd=str(subtitle.parent), error_id='H108')
        os.replace(temp, job_dir / RENDER_OUTPUT)
    finally:
        temp.unlink(missing_ok=True)
    progress(job_dir, 'render', 'VIDEO_RENDERING', 1000, 1000)


def main():
    """`python -m audio_translate.video.merge probe <path>...`: the page's file check, one JSON line."""
    if len(sys.argv) > 2 and sys.argv[1] == 'probe':
        out = []
        for path in sys.argv[2:]:
            try: out.append(probe(path))
            except VideoError as error: out.append({'path': path, 'name': Path(path).name, 'error': error.code})
        print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
