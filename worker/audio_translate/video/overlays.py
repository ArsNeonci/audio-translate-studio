"""Logos and pictures laid on the video (docs/OVERLAYS.md): the picture library, the templates that place them, and what a run keeps of them.

A template is a list of pictures placed on a frame as fractions of its width and height (x, y of the top-left corner, w of the width), so the
same template fits 480p, 720p and 1080p and any clip shape. Each template belongs to one orientation (landscape 16:9 or portrait 9:16, the YouTube
frames the editor draws) and each orientation can have a default that every new video uses.

A run takes a snapshot of the template it uses (job["video"]["overlay"]) and copies the pictures into its own working folder, so editing or deleting
the template or a picture later never breaks a run that is waiting or retried.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from audio_translate.core import storage
from audio_translate.core.storage import atomic_json, file_lock

EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.ico', '.gif'}
MAX_BYTES = 10 * 1024 ** 2
MAX_SIDE = 4096
MAX_ITEMS = 20
MAX_TEMPLATES = 50
MAX_ASSETS = 200
ORIENTATIONS = ('landscape', 'portrait')
ASSET_ID = re.compile(r'[0-9a-f]{32}')
TEMPLATE_ID = re.compile(r'[0-9a-f]{12}')
FOLDER = 'working/overlays'
CHOICES = ('default', 'none')


class OverlayError(ValueError):
    """A problem the person can fix; `code` is shown translated."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def root(): return storage.DATA / 'overlays'


def _store(): return root() / 'overlays.json'


def _empty(): return {'version': 1, 'assets': {}, 'templates': [], 'defaults': {}}


def _read():
    try: value = json.loads(_store().read_text(encoding='utf-8'))
    except (OSError, ValueError): return _empty()
    if not isinstance(value, dict): return _empty()
    return {**_empty(), **value}


class _Locked:
    def __enter__(self):
        self.lock = file_lock(storage.DATA / 'management-locks' / 'overlays.lock'); self.lock.__enter__(); return self
    def __exit__(self, *exc): return self.lock.__exit__(*exc)


def _write(value):
    root().mkdir(parents=True, exist_ok=True)
    atomic_json(_store(), value)


def asset_path(asset_id):
    if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id): raise OverlayError('OVERLAY_NOT_FOUND')
    return root() / 'assets' / f'{asset_id}.png'


def listing():
    data = _read()
    assets = [{'id': key, **value} for key, value in data['assets'].items() if asset_path(key).is_file()]
    assets.sort(key=lambda item: item.get('created_at', ''), reverse=True)
    return {'assets': assets, 'templates': data['templates'], 'defaults': data['defaults']}


def _run(args, **kwargs):
    import os
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=0x08000000 if os.name == 'nt' else 0, **kwargs)


def import_asset(path, name):
    """A picture (PNG, JPG, WEBP, BMP, ICO, GIF's first frame) made into a PNG with its transparency, at most 4096 px a side."""
    path = Path(path)
    name = (name or path.name or '').strip()[:120]
    extension = Path(name).suffix.lower()
    if extension not in EXTENSIONS: raise OverlayError('OVERLAY_TYPE')
    if not path.is_file() or path.stat().st_size == 0: raise OverlayError('OVERLAY_UNREADABLE')
    if path.stat().st_size > MAX_BYTES: raise OverlayError('OVERLAY_TOO_BIG')
    if len(_read()['assets']) >= MAX_ASSETS: raise OverlayError('OVERLAY_LIMIT')
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / ('in' + extension)
        shutil.copyfile(path, source)
        target = Path(folder) / 'out.png'
        # The side limit keeps the largest pictures small; the shrink never enlarges (min), and the alpha channel is kept (rgba).
        done = _run(['ffmpeg', '-hide_banner', '-nostdin', '-y', '-i', str(source), '-frames:v', '1', '-vf',
                     f"scale='min({MAX_SIDE},iw)':'min({MAX_SIDE},ih)':force_original_aspect_ratio=decrease,format=rgba", str(target)], timeout=60)
        if done.returncode or not target.is_file() or target.stat().st_size == 0: raise OverlayError('OVERLAY_UNREADABLE')
        info = _run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'json', str(target)], timeout=30)
        try: stream = json.loads(info.stdout)['streams'][0]; width, height = int(stream['width']), int(stream['height'])
        except (ValueError, KeyError, IndexError): raise OverlayError('OVERLAY_UNREADABLE')
        if width < 1 or height < 1: raise OverlayError('OVERLAY_UNREADABLE')
        digest = hashlib.sha256(target.read_bytes()).hexdigest()[:32]
        with _Locked():
            data = _read()
            (root() / 'assets').mkdir(parents=True, exist_ok=True)
            if not asset_path(digest).is_file(): shutil.copyfile(target, asset_path(digest))
            from datetime import datetime, timezone
            item = {'name': Path(name).stem[:60] or 'image', 'width': width, 'height': height, 'size': asset_path(digest).stat().st_size,
                    'created_at': data['assets'].get(digest, {}).get('created_at') or datetime.now(timezone.utc).isoformat()}
            data['assets'][digest] = item
            _write(data)
    return {'id': digest, **item}


def _used(data, asset_id):
    return any(asset_id == item['asset'] for template in data['templates'] for item in template['items'])


def delete_asset(asset_id):
    asset_path(asset_id)
    with _Locked():
        data = _read()
        if asset_id not in data['assets']: raise OverlayError('OVERLAY_NOT_FOUND')
        if _used(data, asset_id): raise OverlayError('OVERLAY_IN_USE')
        del data['assets'][asset_id]
        _write(data)
        asset_path(asset_id).unlink(missing_ok=True)


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high: raise OverlayError('OVERLAY_INVALID')
    return round(float(value), 5)


def _items(value, assets):
    if not isinstance(value, list) or len(value) > MAX_ITEMS: raise OverlayError('OVERLAY_INVALID')
    items = []
    for item in value:
        if not isinstance(item, dict) or item.get('asset') not in assets: raise OverlayError('OVERLAY_INVALID')
        x, y, w = _number(item.get('x'), 0, 1), _number(item.get('y'), 0, 1), _number(item.get('w'), 0.01, 1)
        if x + w > 1.001: raise OverlayError('OVERLAY_INVALID')
        items.append({'asset': item['asset'], 'x': x, 'y': y, 'w': w, 'opacity': _number(item.get('opacity', 1), 0.1, 1)})
    return items


def save_template(payload):
    """Create (no id) or replace (id) a template; the items are listed back to front (the last one is on top)."""
    if not isinstance(payload, dict): raise OverlayError('OVERLAY_INVALID')
    name = payload.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or re.search(r'[\x00-\x1f<>]', name): raise OverlayError('OVERLAY_INVALID')
    if payload.get('orientation') not in ORIENTATIONS: raise OverlayError('OVERLAY_INVALID')
    with _Locked():
        data = _read()
        items = _items(payload.get('items'), data['assets'])
        wanted = payload.get('id')
        if wanted is not None and (not isinstance(wanted, str) or not TEMPLATE_ID.fullmatch(wanted)): raise OverlayError('OVERLAY_INVALID')
        found = next((t for t in data['templates'] if t['id'] == wanted), None) if wanted else None
        if wanted and not found: raise OverlayError('OVERLAY_NOT_FOUND')
        if not found and len(data['templates']) >= MAX_TEMPLATES: raise OverlayError('OVERLAY_LIMIT')
        if any(t['name'].casefold() == name.strip().casefold() and t is not found for t in data['templates']): raise OverlayError('OVERLAY_NAME_TAKEN')
        template = {'id': wanted or uuid.uuid4().hex[:12], 'name': name.strip(), 'orientation': payload['orientation'], 'items': items}
        if found:
            data['templates'][data['templates'].index(found)] = template
            # A template moved to the other orientation can no longer be that orientation's default.
            for side, chosen in list(data['defaults'].items()):
                if chosen == template['id'] and side != template['orientation']: del data['defaults'][side]
        else: data['templates'].append(template)
        _write(data)
    return template


def delete_template(template_id):
    with _Locked():
        data = _read()
        if not any(t['id'] == template_id for t in data['templates']): raise OverlayError('OVERLAY_NOT_FOUND')
        data['templates'] = [t for t in data['templates'] if t['id'] != template_id]
        data['defaults'] = {side: chosen for side, chosen in data['defaults'].items() if chosen != template_id}
        _write(data)


def set_default(orientation, template_id):
    """The template every new video of that orientation uses; None clears it."""
    if orientation not in ORIENTATIONS: raise OverlayError('OVERLAY_INVALID')
    with _Locked():
        data = _read()
        if template_id is None: data['defaults'].pop(orientation, None)
        else:
            template = next((t for t in data['templates'] if t['id'] == template_id), None)
            if not template: raise OverlayError('OVERLAY_NOT_FOUND')
            if template['orientation'] != orientation: raise OverlayError('OVERLAY_INVALID')
            data['defaults'][orientation] = template_id
        _write(data)


def resolve(choice, clips, current=None):
    """The snapshot a run keeps, or None for no overlay.

    choice: "default" (the default of the first clip's orientation, none if there is none), "none", or a template id.
    current: the snapshot the run already has; the same template id keeps it even after the template was deleted.
    """
    if choice is None: choice = 'default'
    if not isinstance(choice, str) or len(choice) > 40: raise OverlayError('OVERLAY_INVALID')
    if choice == 'none': return None
    data = _read()
    if choice == 'default':
        first = clips[0]
        choice = data['defaults'].get('portrait' if first['height'] > first['width'] else 'landscape')
        if not choice: return None
    template = next((t for t in data['templates'] if t['id'] == choice), None)
    if not template:
        if current and current.get('id') == choice: return current
        raise OverlayError('OVERLAY_NOT_FOUND')
    if not template['items']: return None
    return {'id': template['id'], 'name': template['name'], 'orientation': template['orientation'], 'items': template['items']}


def materialize(job_dir, snapshot):
    """The pictures of a snapshot copied into the run's own working folder."""
    if not snapshot: return
    folder = Path(job_dir) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    for item in snapshot['items']:
        target = folder / f"{item['asset']}.png"
        if target.is_file(): continue
        source = asset_path(item['asset'])
        if not source.is_file(): raise OverlayError('OVERLAY_NOT_FOUND')
        shutil.copyfile(source, target)


def picture(job_dir, asset_id):
    """The picture file of a run: its own copy, else the library's."""
    own = Path(job_dir) / FOLDER / f'{asset_id}.png'
    if own.is_file(): return own
    shared = asset_path(asset_id)
    return shared if shared.is_file() else None


def pixel_items(snapshot, width, height):
    """[(asset, x, y, size, opacity)] in pixels of the output frame; the size is the picture's width, even so the encoder is happy."""
    out = []
    for item in snapshot['items']:
        size = max(2, int(round(item['w'] * width / 2)) * 2)
        out.append((item['asset'], int(round(item['x'] * width)), int(round(item['y'] * height)), size, item.get('opacity', 1)))
    return out
