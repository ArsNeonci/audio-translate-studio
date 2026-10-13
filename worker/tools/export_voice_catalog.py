"""Write worker/config/voice-catalog.json from the local VieNeu presets (run on the build machine).

The Basic installer ships without VieNeu (voice is generated on the VPS); voices.discover() then
reads this catalog. Preview samples are already static files in public/voice-previews.
Usage: python worker/tools/export_voice_catalog.py
"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'worker'))
os.environ.setdefault('HF_HOME', str(ROOT/'data'/'hf-cache'))
os.environ.setdefault('HF_HUB_OFFLINE', '1')

from audio_translate.tts.voices import CATALOG, live_presets  # noqa: E402


def main():
    voices, default = live_presets()
    catalog = {'version': 1, 'engine': 'vieneu-v3turbo', 'default_voice_id': default,
               'voices': [{'id': key, 'label': key, 'description': value.get('description', ''), 'aliases': value.get('aliases', [])}
                          for key, value in voices.items()]}
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(catalog["voices"])} voices -> {CATALOG}')


if __name__ == '__main__': main()
