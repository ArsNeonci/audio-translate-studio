"""yt-dlp updates and the YouTube client order, from the gateway, without reinstalling the app.

YouTube changes often, and a yt-dlp release that worked last week can stop working. The gateway serves a small manifest that the
release owner signs offline (packaging/publish_youtube_update.py). The manifest names the yt-dlp wheels to use and the order of
YouTube clients to try. The app checks it every few hours and when every download attempt fails.

Safety: the manifest is accepted only with a valid Ed25519 signature from a key pinned in worker/config/youtube-update-keys.json,
and only with a serial newer than or equal to the one in use, so an old manifest cannot roll an update back. Each wheel is fetched
through a signed one-hour link from the project bucket and kept only if its size and SHA-256 match the signed manifest. The gateway
itself holds no signing key: a compromised gateway cannot make the app run other code.

Downloads still run from the customer's own connection; nothing about the video passes through the gateway.
"""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import zipfile

from audio_translate.core.storage import DATA, atomic_json, file_lock, read_json

SCHEMA = 1
PACKAGES = ('yt-dlp', 'yt-dlp-ejs')          # the only distributions a manifest may install
MAX_WHEEL = 64 * 1024 * 1024
CHECK_HOURS = 6                              # used until a manifest says otherwise
FORCED_GAP = 15 * 60                         # a failed download asks again at most this often
FAILED_RETRY = 3600                          # after a failed check, try again in an hour rather than at the next interval
# Tried in order until one gives an audio stream. Measured 2026-10-09 on a home connection: the default client was refused
# anonymously while mweb worked; with the saved sign-in default, mweb and tv all worked. Replaced by the manifest's list.
DEFAULT_ATTEMPTS = ({'client': None, 'cookies': False}, {'client': 'mweb', 'cookies': False},
                    {'client': None, 'cookies': True}, {'client': 'mweb', 'cookies': True}, {'client': 'tv', 'cookies': True})
CLIENT = re.compile(r'[a-z][a-z0-9_]{0,39}')
WHEEL = re.compile(r'youtube/[A-Za-z0-9][A-Za-z0-9._+-]{0,150}\.whl')
VERSION = re.compile(r'[0-9][0-9A-Za-z.+-]{0,39}')


def root():
    return DATA / 'ytdlp'


def keys_path():
    return Path(__file__).resolve().parents[2] / 'config' / 'youtube-update-keys.json'


def public_keys():
    try: return [base64.b64decode(k) for k in json.loads(keys_path().read_text(encoding='utf-8')).get('keys', [])]
    except (OSError, ValueError): return []


class ManifestError(ValueError):
    pass


def verify(raw, signature, keys=None):
    """The manifest as a dict, only if one pinned key signed exactly these bytes and every field is in range."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(raw, bytes) or len(raw) > 65536: raise ManifestError('manifest size')
    try: sig = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError): raise ManifestError('signature encoding') from None
    for key in public_keys() if keys is None else keys:
        try: Ed25519PublicKey.from_public_bytes(key).verify(sig, raw); break
        except (InvalidSignature, ValueError): continue
    else: raise ManifestError('signature')
    try: data = json.loads(raw.decode('utf-8'))
    except ValueError: raise ManifestError('json') from None
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or type(data.get('serial')) is not int or data['serial'] < 1: raise ManifestError('header')
    packages = data.get('packages')
    if not isinstance(packages, list) or not 1 <= len(packages) <= len(PACKAGES): raise ManifestError('packages')
    names = set()
    for item in packages:
        if not isinstance(item, dict) or item.get('name') not in PACKAGES or item['name'] in names: raise ManifestError('package name')
        if not (isinstance(item.get('version'), str) and VERSION.fullmatch(item['version'])): raise ManifestError('package version')
        if not (isinstance(item.get('path'), str) and WHEEL.fullmatch(item['path'])): raise ManifestError('package path')
        if type(item.get('size')) is not int or not 0 < item['size'] <= MAX_WHEEL: raise ManifestError('package size')
        if not (isinstance(item.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', item['sha256'])): raise ManifestError('package hash')
        names.add(item['name'])
    if 'yt-dlp' not in names: raise ManifestError('yt-dlp missing')
    attempts = data.get('attempts')
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 12: raise ManifestError('attempts')
    for step in attempts:
        if not isinstance(step, dict) or type(step.get('cookies')) is not bool: raise ManifestError('attempt')
        if step.get('client') is not None and not (isinstance(step['client'], str) and CLIENT.fullmatch(step['client'])): raise ManifestError('attempt client')
    if type(data.get('check_hours', CHECK_HOURS)) is not int or not 1 <= data.get('check_hours', CHECK_HOURS) <= 168: raise ManifestError('check_hours')
    return data


def local_manifest():
    """The verified manifest saved by the last successful check, or None."""
    try: return verify((root() / 'manifest.json').read_bytes(), (root() / 'manifest.sig').read_text(encoding='ascii').strip())
    except (OSError, ManifestError): return None


def release_dir(serial):
    return root() / 'releases' / str(serial)


def installed(manifest):
    marker = release_dir(manifest['serial']) / '.ok'
    try: return json.loads(marker.read_text(encoding='utf-8')) == [p['sha256'] for p in manifest['packages']]
    except (OSError, ValueError): return False


def attempts():
    manifest = local_manifest()
    return [dict(step) for step in (manifest['attempts'] if manifest else DEFAULT_ATTEMPTS)]


def extract(wheel, target):
    """Unpack one wheel (a zip) into target, refusing any entry that would land outside it."""
    base = target.resolve()
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            destination = (base / entry.filename).resolve()
            if not destination.is_relative_to(base) or entry.filename.startswith(('/', '\\')): raise ManifestError('unsafe wheel entry')
        archive.extractall(base)


def install(manifest, urls, opener=None):
    """Fetch, check and unpack every wheel of the manifest into its own release folder; the folder appears only when complete."""
    from audio_translate.transcription.model_prefetch import download_one
    import urllib.request
    opener = opener or urllib.request.urlopen
    downloads = root() / 'downloads'
    work = root() / 'releases' / f".{manifest['serial']}-{os.getpid()}"
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        for item in manifest['packages']:
            url = urls.get(item['path']) if isinstance(urls, dict) else None
            if not isinstance(url, str) or not url.startswith('https://'): raise ManifestError(f"no link for {item['path']}")
            wheel = downloads / Path(item['path']).name
            if not (wheel.is_file() and wheel.stat().st_size == item['size']):
                download_one(url, wheel, item['size'], item['sha256'], lambda *a, **k: None, opener)
            else:
                from audio_translate.core.storage import file_digest
                if file_digest(wheel) != item['sha256']: wheel.unlink(); download_one(url, wheel, item['size'], item['sha256'], lambda *a, **k: None, opener)
            extract(wheel, work)
        (work / '.ok').write_text(json.dumps([p['sha256'] for p in manifest['packages']]), encoding='utf-8')
        target = release_dir(manifest['serial'])
        if target.exists(): shutil.rmtree(target)
        os.replace(work, target)
    finally:
        if work.exists(): shutil.rmtree(work, ignore_errors=True)
    for wheel in downloads.glob('*.whl'):
        if wheel.name not in {Path(p['path']).name for p in manifest['packages']}: wheel.unlink(missing_ok=True)
    keep = {str(manifest['serial'])}
    previous = read_json(root() / 'current.json').get('serial') if (root() / 'current.json').exists() else None
    if previous is not None: keep.add(str(previous))   # a worker that started a moment ago may still read the previous one
    for folder in (root() / 'releases').iterdir():
        if folder.is_dir() and folder.name not in keep and not folder.name.startswith('.'): shutil.rmtree(folder, ignore_errors=True)


def refresh(force=False, post=None, opener=None, now=None):
    """Ask the gateway for the current manifest when it is due. Never raises: a failed check leaves the app on what it has.
    Returns {'changed': bool, 'serial': int|None, 'error': str|None}."""
    now = time.time() if now is None else now
    try:
        root().mkdir(parents=True, exist_ok=True)
        with file_lock(root() / 'update.lock'):
            checked = read_json(root() / 'checked.json') if (root() / 'checked.json').exists() else {}
            manifest = local_manifest()
            current = manifest['serial'] if manifest and installed(manifest) else None
            interval = (manifest or {}).get('check_hours', CHECK_HOURS) * 3600
            due_at = checked.get('next_at', checked['at'] + interval if 'at' in checked else 0)   # never asked: due now
            if force and now - checked.get('forced_at', 0) < FORCED_GAP: return {'changed': False, 'serial': current, 'error': None}
            if not force and now < due_at: return {'changed': False, 'serial': current, 'error': None}
            stamp = {'at': now, **({'forced_at': now} if force else {'forced_at': checked.get('forced_at', 0)})}
            try:
                from audio_translate.translation import genius
                endpoint = genius.settings().get('endpoint') or ''
                if not endpoint: raise RuntimeError('NO_GATEWAY')
                reply = (post or genius.post)(endpoint, '/v1/youtube/update', {'serial': current}, genius.credential(), 20)
                raw, signature = reply.get('manifest'), reply.get('signature')
                if not isinstance(raw, str) or not isinstance(signature, str): raise ManifestError('reply')
                fresh = verify(raw.encode('utf-8'), signature)
                if manifest and fresh['serial'] < manifest['serial']: raise ManifestError('older serial')   # no rollback by replay
                changed = not (manifest and fresh['serial'] == manifest['serial'] and installed(manifest))
                if changed:
                    install(fresh, reply.get('urls'), opener)
                    (root() / 'manifest.sig').write_text(signature.strip(), encoding='ascii')
                    tmp = root() / 'manifest.json.tmp'; tmp.write_bytes(raw.encode('utf-8')); os.replace(tmp, root() / 'manifest.json')
                    atomic_json(root() / 'current.json', {'serial': fresh['serial'], 'installed_at': now})
                atomic_json(root() / 'checked.json', {**stamp, 'next_at': now + fresh.get('check_hours', CHECK_HOURS) * 3600, 'error': None})
                return {'changed': changed, 'serial': fresh['serial'], 'error': None}
            except Exception as exc:
                code = getattr(exc, 'code', None)
                detail = f'MANIFEST_{exc}' if isinstance(exc, ManifestError) else str(code) if code else f'{type(exc).__name__}: {exc}'
                atomic_json(root() / 'checked.json', {**stamp, 'next_at': now + min(interval, FAILED_RETRY), 'error': detail[:200]})
                return {'changed': False, 'serial': current, 'error': detail[:200]}
    except Exception as exc:
        return {'changed': False, 'serial': None, 'error': type(exc).__name__}


def activate():
    """Put the installed release first on sys.path, before yt_dlp is imported. Returns the release's yt-dlp version or None (bundled)."""
    manifest = local_manifest()
    try: current = read_json(root() / 'current.json').get('serial')
    except (OSError, ValueError): current = None
    if not manifest or manifest['serial'] != current or not installed(manifest): return None
    folder = str(release_dir(current))
    if 'yt_dlp' in sys.modules and not str(getattr(sys.modules['yt_dlp'], '__file__', '')).startswith(folder): return None   # too late in this process
    if folder not in sys.path: sys.path.insert(0, folder)
    return next(p['version'] for p in manifest['packages'] if p['name'] == 'yt-dlp')


def info():
    """For Settings: which yt-dlp the next download uses and when the gateway was last asked."""
    manifest = local_manifest()
    try: current = read_json(root() / 'current.json').get('serial')
    except (OSError, ValueError): current = None
    try: checked = read_json(root() / 'checked.json')
    except (OSError, ValueError): checked = {}
    from_gateway = bool(manifest and manifest['serial'] == current and installed(manifest))
    if from_gateway: version = next(p['version'] for p in manifest['packages'] if p['name'] == 'yt-dlp')
    else:
        try:
            from importlib import metadata
            version = metadata.version('yt-dlp')
        except Exception: version = None
    return {'version': version, 'source': 'gateway' if from_gateway else 'bundled', 'serial': current if from_gateway else None,
            'checked_at': checked.get('at'), 'error': checked.get('error')}
