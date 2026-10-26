"""Fine-tuned voices ("voice packs") for the VieNeu v3 Turbo ONNX engine.

A pack is one voice trained with LoRA (voice-clone-lab/finetune). It ships as models/voice-packs/<slug>/:
    voice.json   display fields like a VieNeu preset, the 192-d speaker embedding, the pinned base model
    delta.npz    per backbone matrix: ONNX byte offset, shape and the low-rank factors (left @ right = scale * B @ A, transposed)

The ONNX graphs keep their weights in vieneu_backbone_shared.data (prefill and decode_step share the same offsets),
so the fine-tuned model is the base folder with that one file patched. It is built once per machine into
DATA/voice-packs/<slug>/onnx and loaded with Vieneu(backend="onnx", onnx_dir=...). The voice has no reference
codes: the model was trained on the speaker embedding alone.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

from audio_translate.core.storage import DATA, ROOT, LockedError, atomic_json, file_digest, file_lock, read_json

PACKS = ROOT / 'models' / 'voice-packs'
FORMAT = 'audio-translate-voice-pack/1'
DATA_FILE = 'vieneu_backbone_shared.data'
BASE_FILES = ('vieneu_prefill.onnx', 'vieneu_decode_step.onnx', 'vieneu_acoustic_cached.onnx', 'vieneu_v3_heads.npz', 'config.json', 'tokenizer.json')
_FIELDS = ('description', 'gender', 'region', 'style', 'aliases')


def _read(folder):
    data = read_json(folder / 'voice.json')
    if data.get('format') != FORMAT or not data.get('id') or len(data.get('speaker_emb') or []) != 192:
        raise ValueError(f'Invalid voice pack {folder.name}')
    if not (folder / data['delta']['file']).is_file(): raise ValueError(f'Voice pack {folder.name} has no delta')
    return {**data, 'slug': folder.name, 'folder': folder}


def packs(root=None):
    """{voice id: pack} of the packs shipped with the app. A broken pack is skipped, not fatal for the voice list."""
    found = {}
    root = Path(root or PACKS)
    for folder in sorted(root.iterdir()) if root.is_dir() else ():
        if (folder / 'voice.json').is_file():
            try: pack = _read(folder)
            except (OSError, ValueError, KeyError): continue
            found[pack['id']] = pack
    return found


def find(voice, root=None):
    return packs(root).get(voice)


def preset_entry(pack):
    """The pack as a voices_v3_turbo.json-like entry for the voice list."""
    return {**{key: pack.get(key) for key in _FIELDS}, 'aliases': pack.get('aliases') or [], 'speaker_emb': pack['speaker_emb'], 'codes': None, 'pack': pack['slug']}


def engine_voice(pack):
    import numpy as np
    return {'speaker_emb': np.asarray(pack['speaker_emb'], dtype=np.float32), 'codes': None}


def signature(pack):
    """Identity of the patched model; it changes when the pack or its pinned base changes."""
    return hashlib.sha256(json.dumps([pack['delta']['sha256'], pack['base']], sort_keys=True).encode()).hexdigest()


def base_folder(pack):
    """The pinned base onnx_update folder in the Hugging Face cache (downloaded like the normal engine does)."""
    from huggingface_hub import hf_hub_download
    base = pack['base']
    last = None
    for name in (*BASE_FILES, DATA_FILE):
        last = hf_hub_download(base['repo'], name, subfolder=base['subfolder'], revision=base['revision'])
    return Path(last).parent


def apply_delta(data_path, delta_path):
    """Add each low-rank update to its matrix inside the .data file, in place (memory-mapped, fp32)."""
    import numpy as np
    delta = np.load(delta_path)
    offsets, shapes = delta['offsets'], delta['shapes']
    weights = np.memmap(data_path, dtype=np.uint8, mode='r+')
    try:
        for index, (offset, shape) in enumerate(zip(offsets.tolist(), shapes.tolist())):
            size = shape[0] * shape[1] * 4
            if offset < 0 or offset + size > len(weights): raise ValueError('Voice pack delta does not fit the base weights')
            matrix = weights[offset:offset + size].view(np.float32).reshape(shape)
            matrix += delta[f'left_{index}'] @ delta[f'right_{index}']
        weights.flush()
    finally:
        del weights


def prepare(pack, timeout=900, sleep=time.sleep):
    """Folder of the fine-tuned ONNX model, built on first use. Concurrent TTS workers wait for one builder."""
    target = DATA / 'voice-packs' / pack['slug']
    onnx, marker, wanted = target / 'onnx', target / 'ready.json', signature(pack)
    began = time.monotonic()
    while True:
        if marker.is_file() and read_json(marker).get('signature') == wanted and (onnx / DATA_FILE).is_file():
            return onnx
        try:
            with file_lock(target / 'build.lock'):
                if marker.is_file() and read_json(marker).get('signature') == wanted and (onnx / DATA_FILE).is_file():
                    return onnx
                _build(pack, target, wanted)
                return onnx
        except LockedError:
            if time.monotonic() - began > timeout: raise RuntimeError('Voice pack is still being prepared by another process')
            sleep(1)


def _build(pack, target, wanted):
    if file_digest(pack['folder'] / pack['delta']['file']) != pack['delta']['sha256']: raise ValueError('Voice pack delta is damaged')
    base = base_folder(pack)
    if file_digest(base / DATA_FILE) != pack['base']['data_sha256']: raise ValueError('Voice pack does not match the installed VieNeu model')
    (target / 'ready.json').unlink(missing_ok=True)
    temporary = target / f'onnx.{os.getpid()}.tmp'
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    try:
        for name in BASE_FILES: shutil.copyfile(base / name, temporary / name)
        shutil.copyfile(base / DATA_FILE, temporary / DATA_FILE)
        apply_delta(temporary / DATA_FILE, pack['folder'] / pack['delta']['file'])
        shutil.rmtree(target / 'onnx', ignore_errors=True)
        os.replace(temporary, target / 'onnx')
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    atomic_json(target / 'ready.json', {'signature': wanted, 'voice': pack['id']})
