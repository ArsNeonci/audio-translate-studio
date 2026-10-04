"""Offline system-asset builder. Playback endpoints never import this module."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import wave
from audio_translate.core.storage import ROOT, DATA, atomic_json, read_json, file_digest, file_lock
from audio_translate.core.providers import vieneu_source

ASSETS = ROOT/'public'/'voice-previews'
VERSION = 1
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'PARTIAL', 'DELETING'}


def busy():
    for directory in ('tmp', 'tool-tmp', 'jobs'):
        root = DATA/directory
        if not root.exists():
            continue
        for path in root.glob('*/job.json'):
            try:
                job = read_json(path)
                if job.get('status') not in TERMINAL or any(item.get('state') == 'RUNNING' for item in job.get('steps', {}).values()):
                    return True
            except (OSError, ValueError):
                return True  # Fail closed while the state is unreadable.
    return False


def validate(path):
    with wave.open(str(path), 'rb') as audio:
        if audio.getnchannels() != 1 or audio.getframerate() != 48000 or audio.getnframes() < 2400:
            raise ValueError('Invalid preview audio')
        return round(audio.getnframes() * 1000 / audio.getframerate())


def build(catalog, adapter, allow_active=False):
    ASSETS.mkdir(parents=True, exist_ok=True)
    manifest_path = ASSETS/'manifest.json'
    manifest = read_json(manifest_path) if manifest_path.exists() else {'version': VERSION, 'voices': []}
    previous = {item['id']: item for item in manifest.get('voices', [])}
    current = []
    for voice in catalog['voices']:
        if not allow_active and busy():
            raise RuntimeError('A workflow started; preview generation stopped without touching it')
        name = voice['id']
        text = f'Tên tôi là {name}.'
        recipe = hashlib.sha256(json.dumps({'version':VERSION, 'id':name, 'text':text, 'engine':'v3turbo'}, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        old = previous.get(name)
        if old and old.get('recipe') == recipe and (ASSETS/f"{old['key']}.wav").is_file() and file_digest(ASSETS/f"{old['key']}.wav") == old['key']:
            validate(ASSETS/f"{old['key']}.wav")
            current.append(old)
        else:
            adapter.settings['voice'] = name
            temp = ASSETS/f'{recipe}.tmp.wav'
            try:
                adapter.synthesize(text, temp)
                duration = validate(temp)
                key = file_digest(temp)
                target = ASSETS/f'{key}.wav'
                os.replace(temp, target)
                current.append({'id':name, 'text':text, 'key':key, 'recipe':recipe, 'duration_ms':duration})
            finally:
                temp.unlink(missing_ok=True)
        # Publish only complete, validated files. Preserve other valid existing samples.
        merged = {item['id']:item for item in manifest.get('voices', [])}
        merged.update({item['id']:item for item in current})
        atomic_json(manifest_path, {'version':VERSION, 'voices':list(merged.values())})
        print(f'Preview ready {len(current)}/{len(catalog["voices"])}: {name}', flush=True)
    atomic_json(manifest_path, {'version':VERSION, 'voices':current})
    return len(current)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wait-idle', action='store_true')
    parser.add_argument('--allow-active', action='store_true')
    args = parser.parse_args()
    state = DATA/'config'/'voice-preview-builder.json'
    try:
        with file_lock(DATA/'config'/'voice-preview-builder.lock'):
            if not args.allow_active:
                if busy() and not args.wait_idle:
                    raise RuntimeError('Workflow is active. Use --wait-idle to avoid competing with it.')
                if busy():
                    atomic_json(state, {'status':'WAITING_IDLE'})
                    print('Waiting for workflows to finish; no model loaded.', flush=True)
                while busy():
                    time.sleep(30)
            atomic_json(state, {'status':'BUILDING'})
            # Reuse existing local weights; do not download models in this task.
            os.environ.update(AI_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', HF_HUB_OFFLINE='1')
            # Hub constants are frozen on import: set the app cache before
            # torch/discovery can import huggingface_hub, not only in load().
            os.environ.setdefault('HF_HOME', str(DATA/'hf-cache'))
            import torch
            torch.set_num_threads(1)
            from audio_translate.tts.adapters import TTSAdapter
            from audio_translate.tts.voices import discover
            catalog = discover()
            adapter = TTSAdapter({'source':str(vieneu_source()),
                                  'device':'cpu', 'precision':'fp32', 'voice':catalog['default_voice_id']})
            count = build(catalog, adapter, args.allow_active)
            atomic_json(state, {'status':'READY', 'count':count})
    except Exception as exc:
        atomic_json(state, {'status':'FAILED', 'error':type(exc).__name__})
        raise


if __name__ == '__main__':
    main()
