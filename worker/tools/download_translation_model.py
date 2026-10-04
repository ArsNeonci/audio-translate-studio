"""Download only the pinned GGUF and provenance; no source checkout or Git."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

REPO = 'tencent/Hy-MT2-1.8B-GGUF'
REVISION = 'a0c709d9fac510f2c807aa3af52872340dc37a4a'
FILENAME = 'Hy-MT2-1.8B-Q8_0.gguf'
SIZE = 1908528192
SHA256 = '5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4'
DIRECTORY = Path(__file__).resolve().parents[2] / 'models' / 'Hy-MT2-1.8B-Q8_0'


def download():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = DIRECTORY / FILENAME
    partial = target.with_suffix('.gguf.part')
    if not target.exists():
        for attempt in range(6):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset == SIZE:
                break
            request = urllib.request.Request(
                f'https://huggingface.co/{REPO}/resolve/{REVISION}/{FILENAME}',
                headers={'Range': f'bytes={offset}-'} if offset else {})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    if offset and (response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-')):
                        raise RuntimeError('Server did not honor download resume range')
                    with partial.open('ab' if offset else 'wb') as output:
                        last = time.monotonic()
                        while chunk := response.read(4 * 1024 * 1024):
                            output.write(chunk)
                            offset += len(chunk)
                            if time.monotonic() - last >= 20:
                                print(f'{offset}/{SIZE} bytes ({offset / SIZE:.1%})', flush=True)
                                last = time.monotonic()
                break
            except (OSError, TimeoutError) as exc:
                if attempt == 5:
                    raise
                print(f'Retrying: {exc}', flush=True)
                time.sleep(2)
        if partial.stat().st_size != SIZE:
            raise RuntimeError('Incomplete GGUF download')
        with partial.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != SHA256:
            raise RuntimeError('GGUF checksum mismatch; partial file retained for inspection')
        os.replace(partial, target)
    else:
        with target.open('rb') as stream:
            if target.stat().st_size != SIZE or hashlib.file_digest(stream, 'sha256').hexdigest() != SHA256:
                raise RuntimeError('Existing GGUF checksum mismatch')
    for name, url in {
        'MODEL_CARD.md': f'https://huggingface.co/{REPO}/raw/{REVISION}/README.md',
        'LICENSE': f'https://huggingface.co/{REPO}/raw/{REVISION}/LICENSE.txt',
    }.items():
        (DIRECTORY / name).write_bytes(urllib.request.urlopen(url, timeout=60).read())
    (DIRECTORY / 'provenance.json').write_text(json.dumps({
        'repository': REPO, 'revision': REVISION, 'filename': FILENAME,
        'size': SIZE, 'sha256': SHA256, 'license': 'Apache-2.0',
    }, indent=2) + '\n', encoding='utf-8')
    print(f'Verified {target}: {SHA256}', flush=True)


if __name__ == '__main__':
    download()
