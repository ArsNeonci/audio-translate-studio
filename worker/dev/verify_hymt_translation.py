"""Small real-model acceptance run; never edits or reprocesses user jobs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import argparse
import json
import re
from pathlib import Path
import time

import psutil
from audio_translate.tts.adapters import TranslationAdapter, adapter_settings
from audio_translate.core.license_gate import assert_allowed
from audio_translate.workflow.postprocess import translate, export_translation_partial
from audio_translate.translation.hymt_translation import PROMPT
from audio_translate.core.storage import ROOT, atomic_json, read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--startup-gib', type=float, default=3.5,
                        help='Test-only startup threshold; production remains 3.5 GiB')
    args = parser.parse_args()
    assert_allowed()
    job = ROOT / 'data' / 'verification' / ('hymt-real-translation-' + str(time.time_ns()))
    (job / 'working').mkdir(parents=True, exist_ok=True)
    atomic_json(job / 'job.json', {'status': 'TRANSCRIPTION_COMPLETED'})
    settings = adapter_settings(job)
    settings['translation'].update(n_ctx=4096, source_tokens=768, output_tokens=1536,
                                   n_batch=128, threads=4, startup_available_gib=args.startup_gib, prompt=PROMPT, version=5)
    atomic_json(job / 'working' / 'adapters.json', settings)
    sources = [
        {'start_ms': 0, 'end_ms': 4000, 'text': '你好，欢迎来到我们的频道。今天我们聊一聊怎样把中文翻译得更自然。'},
        {'start_ms': 4000, 'end_ms': 8000, 'text': '我本来想早点出门，结果一看外面下着大雨，只好等雨停了再走。'},
    ]
    (job / 'transcript.zh.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in sources), encoding='utf-8')
    began = time.monotonic()
    adapter = TranslationAdapter(settings['translation'])
    try:
        translate(job, adapter)
        output = [json.loads(line) for line in (job / 'transcript.vi.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [(row['start_ms'], row['end_ms'], row['text_zh']) for row in output] == [(row['start_ms'], row['end_ms'], row['text']) for row in sources]
        assert all(row['text_vi'].strip() and '<think>' not in row['text_vi']
                   and not re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]', row['text_vi']) for row in output)
        assert export_translation_partial(job)['rows'] == len(sources)
        translate(job, adapter)  # Durable completed-stage skip.
        report = {'kind': 'real_hymt2_1_8b_q8_0_translation', 'seconds': round(time.monotonic() - began, 2),
                  'startup_threshold_gib': args.startup_gib, 'production_startup_gib': 3.5,
                  'python_rss_gib': round(psutil.Process().memory_info().rss / 1024**3, 2),
                  'server_rss_gib': round(psutil.Process(adapter.runtime.server.process.pid).memory_info().rss / 1024**3, 2) if adapter.runtime else None,
                  'timestamp_and_resume_verified': True, 'translations': output,
                  'runtime': read_json(job / 'working' / 'translation-runtime.json')}
        atomic_json(job / 'report.json', report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        adapter.close()


if __name__ == '__main__':
    main()
