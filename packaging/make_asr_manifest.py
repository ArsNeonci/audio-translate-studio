"""List the speech-model files (path, size, SHA-256) from a folder that holds the three models, and write the manifest the app and the gateway use.

    python packaging/make_asr_manifest.py --source <ModelScope cache root>      (the folder that contains models/<org>--<name>/snapshots/master)

Writes the same content to:
  audio-translates/worker/config/asr-models.json    the app pins every file's size and SHA-256 from it (a wrong or damaged file is never kept)
  billing-gateway/asr_models.json                   the gateway serves only the files named in it
Then upload the files with:  python packaging/upload_model.py --bucket <bucket> --asr <same folder>
Run it again (and redeploy gateway and build) only when the models change. Not part of the app; needs funasr (the development venv).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from audio_translate.transcription import model_prefetch  # noqa: E402

SKIP_DIRS = {'fig', '.git', '.mdl', '.msc', '.mv'}
SKIP_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.wav', '.md', '.incomplete', '.part', '.lock'}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while block := handle.read(8 * 1024 * 1024): digest.update(block)
    return digest.hexdigest()


def collect(root):
    models = []
    for alias in model_prefetch.ALIASES:
        directory = model_prefetch.model_id(alias).replace('/', '--')
        snapshot = Path(root) / 'models' / directory / 'snapshots' / 'master'
        if not (snapshot / 'config.yaml').is_file() or not (snapshot / 'model.pt').is_file(): raise SystemExit(f'{alias} is not complete in {snapshot}')
        files = []
        for path in sorted(snapshot.rglob('*')):
            relative = path.relative_to(snapshot)
            if not path.is_file() or SKIP_DIRS & set(relative.parts) or path.suffix.lower() in SKIP_SUFFIXES: continue
            files.append({'path': relative.as_posix(), 'size': path.stat().st_size, 'sha256': sha256(path)})
        models.append({'alias': alias, 'dir': directory, 'files': files})
    return {'version': 1, 'models': models}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    manifest = collect(args.source)
    text = json.dumps(manifest, ensure_ascii=False, indent=1) + '\n'
    for target in (ROOT / 'worker' / 'config' / 'asr-models.json', ROOT.parent / 'billing-gateway' / 'asr_models.json'):
        target.write_text(text, encoding='utf-8', newline='\n'); print('wrote', target)
    total = sum(f['size'] for m in manifest['models'] for f in m['files'])
    print(f"{sum(len(m['files']) for m in manifest['models'])} files, {total / 1024 ** 3:.2f} GB")


if __name__ == '__main__':
    main()
