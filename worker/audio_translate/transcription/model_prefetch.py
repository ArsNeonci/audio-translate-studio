"""First run only: fetch the speech models before any ASR worker starts its clock.

The installer does not carry the speech models (about 2 GB). FunASR used to download them inside the worker's start-up, where a
180-second limit applies: on a normal connection the first transcription died at about 54 % of the 990 MB recognition model
("ASR model startup timed out") and every retry hit the same wall. Here every missing file is fetched with no deadline, with progress shown
on the job, resuming a partial file after a dropped connection, and the workers start only when all files exist.

Source: the project's own bucket, through one-hour signed links that the gateway gives to a valid licence (the same place as the translation
model). worker/config/asr-models.json pins every file's size and SHA-256, so a wrong or damaged file is never kept. When the gateway cannot be
used (no licence yet, offline, the bundle not published), the models are fetched from ModelScope exactly as FunASR would.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

from audio_translate.core.control import Cancelled, check_cancel
from audio_translate.core.storage import atomic_json

ALIASES = ('paraformer-zh', 'fsmn-vad', 'ct-punc')   # the three models AutoModel loads (asr_runtime.model)
ATTEMPTS = 6
BUNDLE = 'asr-zh'                                    # the gateway's id of the speech-model bundle
BLOCK = 1024 * 1024


def cache_root():
    return Path(os.environ.get('MODELSCOPE_CACHE') or (Path(os.environ.get('AUDIO_DATA_DIR', 'data')) / 'model-cache'))


def manifest_path():
    return Path(__file__).resolve().parents[2] / 'config' / 'asr-models.json'


def manifest():
    """[(folder, relative path, size, sha256)] of the published bundle, or [] when this build has none."""
    try: data = json.loads(manifest_path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return []
    return [(m['dir'], f['path'], int(f['size']), f['sha256']) for m in data.get('models', []) for f in m.get('files', [])]


def model_id(alias):
    from funasr.download.name_maps_from_hub import name_maps_ms
    return name_maps_ms[alias]


def folder(alias):
    return cache_root() / 'models' / model_id(alias).replace('/', '--')


def present(alias):
    snapshot = folder(alias) / 'snapshots' / 'master'
    return (snapshot / 'config.yaml').is_file() and (snapshot / 'model.pt').is_file()


def missing():
    return [alias for alias in ALIASES if not present(alias)]


def destination(directory, relative):
    return cache_root() / 'models' / directory / 'snapshots' / 'master' / relative


def missing_files():
    """The published files that are not on disk with exactly the published size (a partial file has another name, `.part`)."""
    return [item for item in manifest() if not (destination(item[0], item[1]).is_file() and destination(item[0], item[1]).stat().st_size == item[2])]


def downloaded_bytes(aliases=ALIASES):
    total = 0
    for alias in aliases:
        for path in folder(alias).rglob('*') if folder(alias).exists() else []:
            try: total += path.stat().st_size if path.is_file() else 0
            except OSError: pass
    return total


def fetch(alias):
    """ModelScope: the same call AutoModel makes, so the files land exactly where model_reference() looks for them. Resumes a partial file."""
    from funasr.download.download_model_from_hub import get_or_download_model_dir
    return get_or_download_model_dir(model_id(alias), 'master', is_training=False, check_latest=False)


class Refused(Exception):
    """The signed link was refused (expired): ask for fresh links."""


def download_one(url, path, size, sha256, on_bytes, opener=urllib.request.urlopen):
    """One file, resumable: bytes go to <file>.part and the file appears only when its size and SHA-256 are right."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + '.part')
    offset = part.stat().st_size if part.exists() else 0
    if offset > size: part.unlink(); offset = 0
    if offset < size:
        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
        try: response = opener(request, timeout=60)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403): raise Refused() from None
            raise
        with response:
            if offset and getattr(response, 'status', 206) != 206: offset = 0   # the server ignored the range: start again
            with part.open('ab' if offset else 'wb') as out:
                on_bytes(offset, replace=True)
                while True:
                    block = response.read(BLOCK)
                    if not block: break
                    out.write(block); on_bytes(len(block))
    if part.stat().st_size != size:
        raise IOError('incomplete download')
    digest = hashlib.sha256()
    with part.open('rb') as handle:
        while block := handle.read(8 * BLOCK): digest.update(block)
    if digest.hexdigest() != sha256:
        part.unlink(); raise ValueError('CHECKSUM_MISMATCH')   # a wrong file is never kept; the next attempt starts clean
    os.replace(part, path)


def fetch_bundle(job_dir, files, publish, post=None, opener=urllib.request.urlopen, sleep=time.sleep, interval=1.0):
    """Download `files` [(folder, path, size, sha256)] through signed links from the gateway. Raises on any failure so the caller can fall back."""
    from audio_translate.translation import genius
    settings = genius.settings()
    endpoint = settings.get('endpoint') or ''
    if not endpoint: raise RuntimeError('no gateway')
    post = post or genius.post
    token = genius.credential()
    all_files = manifest()
    total = sum(item[2] for item in all_files)
    state = {'done': total - sum(item[2] for item in files), 'part': 0}   # bytes of the files already complete + of the file in progress
    counter = {'file': 0}
    stop = threading.Event()

    def on_bytes(count, replace=False):
        if replace: state['part'] = count
        else: state['part'] += count

    def report():
        publish(source='gateway', downloaded_gib=round((state['done'] + state['part']) / 1024 ** 3, 2), total_gib=round(total / 1024 ** 3, 2),
                file_index=counter['file'], file_total=len(files))

    def watch():
        while not stop.wait(interval): report()

    watcher = threading.Thread(target=watch, daemon=True); watcher.start()
    links = {}
    try:
        # Small files first, the big model files last: the app is usable as early as possible and a dropped link costs the least.
        for position, (directory, relative, size, sha256) in enumerate(sorted(files, key=lambda item: item[2]), 1):
            counter['file'] = position; state['part'] = 0
            key = f'{directory}/{relative}'
            for attempt in range(1, ATTEMPTS + 1):
                check_cancel(job_dir)
                try:
                    if key not in links:
                        pending = [f'{d}/{r}' for d, r, s, _ in files if not (destination(d, r).is_file() and destination(d, r).stat().st_size == s)]
                        links = post(endpoint, '/v1/model/url', {'model': BUNDLE, 'paths': pending[:100]}, token, 30)['urls']
                    download_one(links[key], destination(directory, relative), size, sha256, on_bytes, opener)
                    break
                except Refused:
                    links = {}                          # expired: fresh links on the next attempt
                except Cancelled: raise
                except Exception:
                    if attempt == ATTEMPTS: raise
                    sleep(min(30, 3 * attempt))         # the partial file is kept; the next try continues from it
            state['done'] += size; state['part'] = 0
    finally:
        stop.set(); watcher.join(2)
    report()


def ensure_models(job_dir, download=fetch, sleep=time.sleep, interval=1.0, bundle=None, post=None, opener=urllib.request.urlopen):
    """Download every missing model. Returns True when something was downloaded, False when everything was already there."""
    files, todo = missing_files(), missing()
    if not files and not todo: return False
    job_dir = Path(job_dir); state_path = job_dir / 'working' / 'asr-runtime.json'
    state = {'state': 'DOWNLOADING_MODELS', 'model_total': len(todo) or 1, 'model_index': 0, 'downloaded_gib': 0.0}

    def publish(**changes):
        state.update(changes)
        try: atomic_json(state_path, state)
        except OSError: pass

    publish()
    if files:
        try:
            run = bundle or (lambda job, wanted, report: fetch_bundle(job, wanted, report, post=post, opener=opener, sleep=sleep, interval=interval))
            run(job_dir, files, publish)
        except Cancelled: raise
        except Exception: pass                 # the gateway could not serve it: ModelScope below does the same job, a bit slower
        todo = missing()
    for position, alias in enumerate(todo, 1):
        stop = threading.Event()

        def watch():
            while not stop.wait(interval):
                publish(downloaded_gib=round(downloaded_bytes() / 1024 ** 3, 2))

        publish(source='modelscope', total_gib=None, model_index=position, model_total=len(todo), downloaded_gib=round(downloaded_bytes() / 1024 ** 3, 2))
        watcher = threading.Thread(target=watch, daemon=True); watcher.start()
        try:
            for attempt in range(1, ATTEMPTS + 1):
                check_cancel(job_dir)
                try:
                    download(alias); break
                except Exception as error:
                    if attempt == ATTEMPTS:
                        raise RuntimeError('Không tải được mô hình nhận dạng giọng nói (kiểm tra kết nối mạng). Phần đã tải được giữ lại: bấm Chạy lại giai đoạn để tải tiếp.') from error
                    sleep(min(30, 3 * attempt))   # the partial file is kept; the next try continues from it
        finally:
            stop.set(); watcher.join(2)
    if missing():
        raise RuntimeError('Mô hình nhận dạng giọng nói tải chưa đủ. Bấm Chạy lại giai đoạn để tải tiếp.')
    publish(downloaded_gib=round(downloaded_bytes() / 1024 ** 3, 2), state='MODELS_READY')
    return True
