"""App updates from the gateway (3.2.0): the app finds out by itself that a newer release exists, and the person decides to install it.

The owner builds and tests a release, then publishes it (packaging/publish_update.py): the files go to the gateway server and a manifest naming them
is signed offline. The app asks the gateway for that manifest when it is online (when it opens and every few hours), and offers the update.

Two kinds of package, chosen by the app:
  app        the application without runtime/ and providers/ (the 1.6 GB that rarely changes): tens of MB. Used when the runtime the release needs is
             the one installed (runtime_sha256 equal to this installation's runtime-fingerprint.json). updater.exe applies it after the app quits and
             rolls back by itself if the new version does not report ready.
  installer  the full installer: used when the runtime changed. The updater runs it silently, then starts the app.

Trust: an update is code that runs on this PC, so nothing counts unless the manifest carries a valid Ed25519 signature from a key pinned in
worker/config/app-update-keys.json (the private key stays offline with the owner; the gateway holds none), names this installation's product, is
not older than the last one seen, and the package matches the SHA-256 and size inside it. The version number is information: it does not decide
the licence, and a newer release is offered only when it is newer than the installed one (or the owner allowed a downgrade).
"""
import base64
import json
import os
from pathlib import Path
import re
import threading
import time
import zipfile

from audio_translate.core.storage import DATA, ROOT, atomic_json, file_digest, file_lock, read_json

SCHEMA = 1
CHANNEL = re.compile(r'[a-z][a-z0-9]{0,11}')
VERSION = re.compile(r'\d+\.\d+\.\d+')
HEX64 = re.compile(r'[0-9a-f]{64}')
FILE = re.compile(r'updates/([a-z0-9][a-z0-9-]{1,60})/(\d+\.\d+\.\d+)/([A-Za-z0-9][A-Za-z0-9._+-]{0,120}\.(?:zip|exe))')
LIMITS = {'app': 512 * 1024 ** 2, 'installer': int(3.5 * 1024 ** 3)}   # a Windows .exe must stay under 4 GiB
KINDS = {'app': '.zip', 'installer': '.exe'}
CHECK_SECONDS, FAILED_RETRY, FORCED_GAP = 6 * 3600, 3600, 30
NOTE_LIMIT = 2000


class ManifestError(ValueError):
    pass


def root():
    return DATA / 'updates'


def channel():
    """The release channel: "stable", or another one (e.g. "test") named by AUDIO_UPDATE_CHANNEL. A channel only chooses which signed manifest is read."""
    value = os.environ.get('AUDIO_UPDATE_CHANNEL', 'stable')
    return value if CHANNEL.fullmatch(value) else 'stable'


def keys_path():
    return Path(__file__).resolve().parents[2] / 'config' / 'app-update-keys.json'


def public_keys():
    try: return [base64.b64decode(k) for k in json.loads(keys_path().read_text(encoding='utf-8')).get('keys', [])]
    except (OSError, ValueError): return []


def product_id():
    try: return json.loads((ROOT / 'licensing' / 'public-config.json').read_text(encoding='utf-8-sig')).get('product_id')
    except (OSError, ValueError): return None


def installed_version():
    from audio_translate.api.license import app_version
    return app_version()


def installed_runtime():
    """The fingerprint of the runtime (Python, ffmpeg, node, TTS provider) this installation was built with; None in a development checkout."""
    try:
        value = json.loads((ROOT / 'runtime-fingerprint.json').read_text(encoding='utf-8')).get('sha256')
        return value if isinstance(value, str) and HEX64.fullmatch(value) else None
    except (OSError, ValueError): return None


def number(version):
    """(major, minor, patch) of x.y.z, or None."""
    return tuple(int(p) for p in version.split('.')) if isinstance(version, str) and VERSION.fullmatch(version) else None


def install_root():
    """The installation folder (it holds AudioTranslate.exe and updater.exe), or None when this is not an installed copy."""
    base = ROOT.parent
    return base if ROOT.name == 'app' and (base / 'AudioTranslate.exe').is_file() and (base / 'updater.exe').is_file() else None


def verify(raw, signature, keys=None, product=None, expect_channel=None):
    """The manifest as a dict, only if one pinned key signed exactly these bytes, it is for this product and channel, and every field is in range."""
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
    product = product if product is not None else product_id()
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or type(data.get('serial')) is not int or data['serial'] < 1: raise ManifestError('header')
    if data.get('product') != product or not product: raise ManifestError('product')
    if data.get('channel') != (expect_channel or channel()): raise ManifestError('channel')
    if not (isinstance(data.get('version'), str) and VERSION.fullmatch(data['version'])): raise ManifestError('version')
    if not isinstance(data.get('released_at'), str) or len(data['released_at']) > 40: raise ManifestError('released_at')
    notes = data.get('notes', {})
    if not isinstance(notes, dict) or not all(isinstance(k, str) and len(k) <= 8 and isinstance(v, str) and len(v) <= NOTE_LIMIT for k, v in notes.items()): raise ManifestError('notes')
    if not (isinstance(data.get('runtime_sha256'), str) and HEX64.fullmatch(data['runtime_sha256'])): raise ManifestError('runtime')
    if data.get('min_version') is not None and not (isinstance(data['min_version'], str) and VERSION.fullmatch(data['min_version'])): raise ManifestError('min_version')
    if type(data.get('allow_downgrade', False)) is not bool: raise ManifestError('allow_downgrade')
    packages = data.get('packages')
    if not isinstance(packages, list) or not 1 <= len(packages) <= len(KINDS): raise ManifestError('packages')
    seen = set()
    for item in packages:
        kind = item.get('kind') if isinstance(item, dict) else None
        if kind not in KINDS or kind in seen: raise ManifestError('package kind')
        seen.add(kind)
        match = FILE.fullmatch(item.get('path') if isinstance(item.get('path'), str) else '')
        if not match or match[1] != product or match[2] != data['version'] or not match[3].endswith(KINDS[kind]): raise ManifestError('package path')
        if type(item.get('size')) is not int or not 0 < item['size'] <= LIMITS[kind]: raise ManifestError('package size')
        if not (isinstance(item.get('sha256'), str) and HEX64.fullmatch(item['sha256'])): raise ManifestError('package hash')
    return data


def local_manifest():
    """The verified manifest saved by the last successful check, or None."""
    try: return verify((root() / 'manifest.json').read_bytes(), (root() / 'manifest.sig').read_text(encoding='ascii').strip())
    except (OSError, ManifestError): return None


def failed_versions():
    try:
        value = json.loads((root() / 'failed-versions.json').read_text(encoding='utf-8'))
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
    except (OSError, ValueError): return []


def choose(manifest):
    """(package, kind) this installation should take for the manifest, or (None, None): the app package when the runtime is the one installed,
    otherwise the full installer."""
    by_kind = {item['kind']: item for item in manifest['packages']}
    if 'app' in by_kind and installed_runtime() and installed_runtime() == manifest['runtime_sha256'] and install_root(): return by_kind['app'], 'app'
    if 'installer' in by_kind: return by_kind['installer'], 'installer'
    return None, None


def offer(manifest=None):
    """What to show: the release on offer, or None when there is nothing newer (or this is a development checkout)."""
    manifest = manifest or local_manifest()
    current = number(installed_version())
    if not manifest or current is None: return None
    new = number(manifest['version'])
    if not (new > current or (manifest.get('allow_downgrade') and new != current)): return None
    package, kind = choose(manifest)
    if not package: return None
    minimum = number(manifest.get('min_version')) if manifest.get('min_version') else None
    return {'version': manifest['version'], 'serial': manifest['serial'], 'notes': manifest.get('notes', {}), 'released_at': manifest['released_at'], 'kind': kind,
            'size': package['size'], 'required': bool(minimum and current < minimum), 'failed_before': manifest['version'] in failed_versions(),
            'downgrade': new < current}


# --- asking the gateway ---------------------------------------------------------------------------------------------------------------
_urls = {'at': 0.0, 'urls': {}}


def check(force=False, post=None, now=None):
    """Ask the gateway for the current manifest when it is due. Never raises: a failed check leaves the app on what it has.
    Returns {'changed': bool, 'error': str|None}."""
    now = time.time() if now is None else now
    try:
        root().mkdir(parents=True, exist_ok=True)
        with file_lock(root() / 'update.lock'):
            checked = read_json(root() / 'checked.json') if (root() / 'checked.json').exists() else {}
            if force and now - checked.get('forced_at', 0) < FORCED_GAP: return {'changed': False, 'error': None}
            if not force and now < checked.get('next_at', 0): return {'changed': False, 'error': None}
            stamp = {'at': now, 'forced_at': now if force else checked.get('forced_at', 0)}
            try:
                from audio_translate.translation import genius
                endpoint = genius.settings().get('endpoint') or ''
                if not endpoint: raise RuntimeError('NO_GATEWAY')
                reply = (post or genius.post)(endpoint, '/v1/app/update', {'channel': channel()}, genius.credential(), 20)
                raw, signature = reply.get('manifest'), reply.get('signature')
                if not isinstance(raw, str) or not isinstance(signature, str): raise ManifestError('reply')
                fresh = verify(raw.encode('utf-8'), signature)
                known = local_manifest()
                if known and fresh['serial'] < known['serial']: raise ManifestError('older serial')   # no rollback by replaying an old manifest
                changed = not known or fresh['serial'] != known['serial']
                if changed:
                    (root() / 'manifest.sig').write_text(signature.strip(), encoding='ascii')
                    tmp = root() / 'manifest.json.tmp'; tmp.write_bytes(raw.encode('utf-8')); os.replace(tmp, root() / 'manifest.json')
                urls = reply.get('urls')
                if isinstance(urls, dict): _urls.update(at=now, urls={k: v for k, v in urls.items() if isinstance(k, str) and isinstance(v, str) and v.startswith(('https://', 'http://127.0.0.1'))})
                atomic_json(root() / 'checked.json', {**stamp, 'next_at': now + CHECK_SECONDS, 'error': None})
                return {'changed': changed, 'error': None}
            except Exception as exc:
                code = getattr(exc, 'code', None)
                detail = f'MANIFEST_{exc}' if isinstance(exc, ManifestError) else str(code) if code else f'{type(exc).__name__}: {exc}'
                atomic_json(root() / 'checked.json', {**stamp, 'next_at': now + FAILED_RETRY, 'error': detail[:200]})
                return {'changed': False, 'error': detail[:200]}
    except Exception as exc:
        return {'changed': False, 'error': type(exc).__name__}


def check_in_background(force=False):
    threading.Thread(target=check, args=(force,), daemon=True).start()


# --- downloading ----------------------------------------------------------------------------------------------------------------------
_download = {'state': 'idle', 'done': 0, 'total': 0, 'error': None, 'version': None}
_lock = threading.Lock()


def pending_dir():
    return root() / 'pending'


def ready(full=False):
    """The downloaded and verified package of the release on offer, or None. The status is asked every few seconds, so by default the file is only checked for
    size and time against what the download recorded (it was hashed then); `full` hashes it again, which is done once, right before it is applied."""
    try: marker = read_json(pending_dir() / 'ready.json')
    except (OSError, ValueError): return None
    current, on_offer = installed_version(), offer()
    package = Path(marker.get('package', ''))
    if not on_offer or marker.get('version') != on_offer['version'] or marker.get('kind') != on_offer['kind'] or marker.get('serial') != on_offer['serial']: return None
    if not package.is_file() or package.parent != pending_dir() or marker.get('from_version') != current: return None
    info = package.stat()
    if info.st_size != marker.get('size') or info.st_mtime_ns != marker.get('mtime_ns'): return None
    if full and file_digest(package) != marker.get('sha256'): return None
    return marker


def check_app_package(path, manifest):
    """An app package must hold only what updater.exe may replace, and be this release for this product with this installation's runtime."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name in names:
            parts = name.replace('\\', '/').split('/')
            if name.startswith(('/', '\\')) or '..' in parts or ':' in parts[0]: raise ManifestError('unsafe package entry')
            if parts[0] in ('runtime', 'providers'): raise ManifestError('package carries the runtime')
        config = json.loads(archive.read('app/licensing/public-config.json').decode('utf-8-sig'))
        if config.get('product_id') != manifest['product'] or config.get('version') != manifest['version']: raise ManifestError('package is another release')
        fingerprint = json.loads(archive.read('app/runtime-fingerprint.json').decode('utf-8')).get('sha256')
        if fingerprint != installed_runtime() or fingerprint != manifest['runtime_sha256']: raise ManifestError('package needs another runtime')
        for required in ('AudioTranslate.exe', 'updater.exe', 'app/security-core/bin/audio-security-core.exe'):
            if required not in names: raise ManifestError(f'package lacks {required}')


def download_state():
    with _lock: return dict(_download)


def start_download(post=None, opener=None):
    """Download and check the package of the release on offer in the background. Returns False when nothing is on offer or it is already running."""
    manifest = local_manifest()
    wanted = offer(manifest) if manifest else None
    if not wanted: return False
    with _lock:
        if _download['state'] == 'downloading': return False
        _download.update(state='downloading', done=0, total=wanted['size'], error=None, version=wanted['version'])
    threading.Thread(target=_download_worker, args=(manifest, wanted, post, opener), daemon=True).start()
    return True


def _download_worker(manifest, wanted, post, opener):
    from audio_translate.transcription.model_prefetch import download_one
    import urllib.request
    try:
        package, kind = choose(manifest)
        # Links last an hour; ask again so that a download started long after the last check still has a fresh one. (A check forced a moment ago
        # is not repeated, and after a restart its links are gone: wait out that short gap once.)
        url = None
        for attempt in range(2):
            check(True, post)
            url = _urls['urls'].get(package['path'])
            if url: break
            time.sleep(FORCED_GAP + 1)
        if not url: raise ManifestError('no link for the package')
        target = pending_dir() / Path(package['path']).name
        pending_dir().mkdir(parents=True, exist_ok=True)
        for stale in pending_dir().iterdir():
            if stale.name != target.name + '.part' and stale != target: stale.unlink(missing_ok=True)
        (pending_dir() / 'ready.json').unlink(missing_ok=True)

        def progress(count, replace=False):
            with _lock: _download['done'] = count if replace else _download['done'] + count
        download_one(url, target, package['size'], package['sha256'], progress, opener or urllib.request.urlopen)
        if kind == 'app': check_app_package(target, manifest)
        info = target.stat()
        atomic_json(pending_dir() / 'ready.json', {'version': manifest['version'], 'serial': manifest['serial'], 'kind': kind, 'package': str(target),
                                                    'sha256': package['sha256'], 'from_version': installed_version(), 'size': info.st_size, 'mtime_ns': info.st_mtime_ns})
        with _lock: _download.update(state='ready', done=package['size'], error=None)
    except Exception as exc:
        code = getattr(exc, 'code', None)
        detail = f'MANIFEST_{exc}' if isinstance(exc, ManifestError) else str(code) if code else str(exc) or type(exc).__name__
        with _lock: _download.update(state='failed', error=detail[:200])


# --- applying ---------------------------------------------------------------------------------------------------------------------------
def write_plan(marker):
    """The plan updater.exe follows once the shell has gone (the shell starts it as it exits)."""
    folder = install_root()
    if not folder: raise ManifestError('NOT_INSTALLED')
    wanted = offer()
    plan = {'kind': marker['kind'], 'package': marker['package'], 'sha256': marker['sha256'], 'version': marker['version'], 'from_version': marker['from_version'],
            'install_root': str(folder), 'data': str(DATA), 'allow_downgrade': bool(wanted and wanted['downgrade'])}
    atomic_json(root() / 'apply.json', plan)
    return plan


def write_health():
    """Tells updater.exe that this version started: data/updates/health.json with the version. Written once the API accepts connections."""
    try:
        version = installed_version()
        if version:
            root().mkdir(parents=True, exist_ok=True)
            atomic_json(root() / 'health.json', {'version': version, 'at': time.time(), 'pid': os.getpid()})
    except Exception:
        pass


def last_result():
    """How the last update ended (written by updater.exe), until the person has seen it."""
    try:
        result = read_json(root() / 'last-update.json')
        seen = read_json(root() / 'last-update.seen.json') if (root() / 'last-update.seen.json').exists() else {}
    except (OSError, ValueError): return None
    return None if seen.get('at') == result.get('at') else result


def acknowledge():
    try: atomic_json(root() / 'last-update.seen.json', {'at': read_json(root() / 'last-update.json').get('at')})
    except (OSError, ValueError): pass


def status():
    current = installed_version()
    try: checked = read_json(root() / 'checked.json')
    except (OSError, ValueError): checked = {}
    wanted = offer()
    is_ready = bool(wanted and ready())
    download = download_state() if wanted else {'state': 'idle', 'done': 0, 'total': 0, 'error': None, 'version': None}
    if is_ready and download['state'] != 'downloading': download = {'state': 'ready', 'done': wanted['size'], 'total': wanted['size'], 'error': None, 'version': wanted['version']}
    return {'installed': {'version': current, 'product': product_id(), 'runtime': installed_runtime(), 'can_update': bool(install_root())},
            'channel': channel(), 'offer': wanted, 'download': download, 'ready': is_ready, 'checked_at': checked.get('at'), 'error': checked.get('error'), 'last_result': last_result()}
