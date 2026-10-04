"""Install the pinned official Windows CPU llama-server runtime."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

from audio_translate.core.storage import ROOT

VERSION = 'b11379'
FILENAME = f'llama-{VERSION}-bin-win-cpu-x64.zip'
URL = f'https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/{FILENAME}'
SHA256 = 'ec014c2c2a27b18786d24eba3e8650d4e68b9003ca6cf91714125b71975eb7ea'
LICENSE_URL = f'https://raw.githubusercontent.com/ggml-org/llama.cpp/{VERSION}/LICENSE'
LICENSE_SHA256 = '94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d'
DIRECTORY = ROOT / 'runtime' / 'llama'


def needed(name):
    """Server dependencies and CPU variants only; no CLI/benchmark tools."""
    return (name in {'llama-server.exe', 'llama-server-impl.dll', 'llama-common.dll',
                     'llama.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-rpc.dll',
                     'libomp.dll', 'mtmd.dll'}
            or name.startswith('ggml-cpu-') and name.endswith('.dll')
            or name.startswith('LICENSE'))


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    archive = DIRECTORY / (FILENAME + '.tmp')
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL, timeout=60) as response, archive.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        if checksum != SHA256:
            raise RuntimeError('llama runtime checksum mismatch')
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                destination = (DIRECTORY / entry.filename).resolve()
                if not destination.is_relative_to(DIRECTORY.resolve()):
                    raise RuntimeError('Unsafe runtime archive path')
            for entry in package.infolist():
                if needed(Path(entry.filename).name):
                    package.extract(entry, DIRECTORY)
        if not (DIRECTORY / 'llama-server.exe').exists():
            raise RuntimeError('Runtime archive did not contain llama-server.exe')
        license_text = opener.open(LICENSE_URL, timeout=30).read()
        if hashlib.sha256(license_text).hexdigest() != LICENSE_SHA256:
            raise RuntimeError('llama runtime license checksum mismatch')
        (DIRECTORY / 'LICENSE-llama.cpp').write_bytes(license_text)
        files = {str(p.relative_to(DIRECTORY)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in DIRECTORY.rglob('*') if p.is_file() and p != archive and p.name != 'provenance.json'}
        (DIRECTORY / 'provenance.json').write_text(json.dumps(
            {'version': VERSION, 'url': URL, 'archive_sha256': SHA256, 'files': files}, indent=2), encoding='utf-8')
        print(f'Installed verified llama-server {VERSION}: {DIRECTORY}')
    finally:
        archive.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
