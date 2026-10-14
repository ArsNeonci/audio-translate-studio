"""Fill an empty data folder with known workflows for the app API contract tests.

    .venv\\Scripts\\python.exe contracts\\tests\\seed_app_data.py <empty data folder>

Prints a JSON object with the ids it created. Uses the worker's own code with the fake translator and voice of the
worker tests, so no model, network or licence is needed. Never point it at the real data folder.
"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(sys.argv[1]).resolve()
if (DATA / 'tmp').exists() or (DATA / 'results').exists(): raise SystemExit(f'Not an empty data folder: {DATA}')
os.environ['AUDIO_DATA_DIR'] = str(DATA)
os.environ['RESULTS_ROOT'] = str(DATA / 'results')
sys.path.insert(0, str(ROOT / 'worker'))

from audio_translate.core.errors import STEPS  # noqa: E402
from audio_translate.core.storage import read_json, update_job  # noqa: E402
from audio_translate.moderation.rules import ReplacementRules  # noqa: E402
from audio_translate.tts import voices  # noqa: E402
from audio_translate.workflow import manage, results  # noqa: E402
from audio_translate.workflow.orchestrator import run  # noqa: E402
from audio_translate.workflow.postprocess import moderate, synthesize, translate  # noqa: E402
from tests.test_postprocess import FakeTranslator, FakeTTS  # noqa: E402

URL = 'https://youtu.be/1JzKgwOESoM'


def transcribed(job_dir):
    """Mark Download and Transcription done and write a two-line Chinese transcript."""
    steps = read_json(job_dir / 'job.json')['steps']
    for step in STEPS[:2]: steps[step]['state'] = 'COMPLETED'
    update_job(job_dir, steps=steps)
    lines = [{'start_ms': 0, 'end_ms': 1000, 'text': '你好'}, {'start_ms': 1000, 'end_ms': 2000, 'text': '谢谢'}]
    (job_dir / 'transcript.zh.md').write_text('你好\n\n谢谢', encoding='utf-8')
    (job_dir / 'transcript.zh.jsonl').write_text(''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in lines), encoding='utf-8')


def completed(voice, rules):
    job_dir = results.workspace(manage.create(URL, voice)['id'])
    transcribed(job_dir)
    def child(command, **kwargs):
        stage = command[-1]
        if stage == 'translation': translate(job_dir, FakeTranslator())
        elif stage == 'moderation': moderate(job_dir, rules)
        elif stage == 'tts': synthesize(job_dir, FakeTTS())
        elif stage == 'subtitle':
            from audio_translate.video.subtitles import run as build_subtitles
            build_subtitles(job_dir)
        else: raise AssertionError(f'unexpected stage {stage}')
        return Mock(returncode=0)
    with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=child):
        if run(job_dir) != 0: raise SystemExit('seed workflow did not complete')
    return job_dir.name


def tool_run():
    upload = DATA / 'uploads' / 'seed.upload'
    upload.parent.mkdir(parents=True, exist_ok=True)
    upload.write_text('你好\n谢谢\n', encoding='utf-8')
    return manage.create(tool='translation', upload=upload, input_name='input.txt', mime='text/plain')['id']


def main():
    with patch('audio_translate.core.license_gate.assert_allowed', return_value=True):
        manage.migrate()
        voice = voices.discover()['voices'][0]['id']
        rules = ReplacementRules(DATA / 'config')
        rule = rules.mutate('add', {'source': '谢谢', 'replacement': 'cảm ơn'})['rules'][0]['id']
        ids = {'completed': completed(voice, rules), 'queued': manage.create(URL, voice)['id'], 'queued2': manage.create(URL, voice)['id'],
               'tool': tool_run(), 'voice': voice, 'rule': rule}
    print(json.dumps(ids))


if __name__ == '__main__':
    main()
