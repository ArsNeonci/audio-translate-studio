"""Read the same preset files and repository default used by VieNeu v3turbo."""
import ast
import os
from pathlib import Path
from storage import ROOT, DATA, read_json, atomic_json, file_lock
from providers import vieneu_source

def discover():
    source = vieneu_source()/'src'/'vieneu'
    tree = ast.parse((source/'v3turbo.py').read_text(encoding='utf-8'))
    repo = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '__init__':
            for arg, value in zip(node.args.args[-len(node.args.defaults):], node.args.defaults):
                if arg.arg == 'backbone_repo' and isinstance(value, ast.Constant): repo = value.value
    config = read_json(source/'assets'/'voices_v3_turbo.json')
    voices = dict(config.get('presets', config.get('voices', {})))
    default = config.get('default_voice')
    # Use cached model metadata; discovery must not load a model or duplicate weights.
    if repo:
        try:
            from huggingface_hub import hf_hub_download
            cached = str(Path(repo)/'voices_v3_turbo.json') if Path(repo).is_dir() else hf_hub_download(repo, 'voices_v3_turbo.json', local_files_only=True)
            extra = read_json(cached)
            voices.update({name:value for name,value in extra.get('presets',extra.get('voices',{})).items() if value.get('speaker_emb') is not None})
            default = extra.get('default_voice', default)
        except (ImportError, OSError): pass
    if not voices: raise ValueError('VieNeu has no available voice presets')
    items = [{'id': key, 'label': key, 'description': value.get('description', ''), 'aliases': value.get('aliases', [])} for key, value in voices.items()]
    if default not in voices: default = items[0]['id']
    settings = DATA/'config'/'preferences.json'
    preferred = read_json(settings).get('last_vietnamese_voice_id') if settings.exists() else None
    return {'voices': items, 'default_voice_id': default, 'selected_voice_id': preferred if preferred in voices else default}

def select(voice=None):
    catalog = discover()
    chosen = voice or catalog['selected_voice_id']
    if chosen not in {v['id'] for v in catalog['voices']}: raise ValueError('Voice is unavailable; choose an available VieNeu preset')
    with file_lock(DATA/'config'/'preferences.lock'):
        atomic_json(DATA/'config'/'preferences.json', {'last_vietnamese_voice_id': chosen})
    return chosen
