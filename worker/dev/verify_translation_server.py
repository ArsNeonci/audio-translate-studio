"""Real-model resource admission acceptance in an isolated fixture, not user jobs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import argparse
import json
import os
from pathlib import Path
import time
import psutil
from audio_translate.tts.adapters import adapter_settings, TranslationAdapter
from audio_translate.core.license_gate import assert_allowed
from audio_translate.workflow.postprocess import translate, export_translation_partial
from audio_translate.core.storage import ROOT, atomic_json, read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--startup-gib', type=float, default=3.5)
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    assert_allowed()
    job = ROOT / 'data' / 'verification' / ('hymt-slots-' + str(time.time_ns()))
    (job / 'working').mkdir(parents=True)
    atomic_json(job / 'job.json', {'status': 'TRANSCRIPTION_COMPLETED'})
    policy = read_json(ROOT / 'worker' / 'config' / 'translation-runtime.json')
    if args.quick:
        policy.update(max_slots=2, threads=4, n_batch=128, scale_up_seconds=1)
    policy['start_free_gib'] = args.startup_gib
    atomic_json(job / 'runtime-policy.json', policy)
    os.environ['HY_MT_RUNTIME_CONFIG'] = str(job / 'runtime-policy.json')
    config = adapter_settings(job)
    config['translation'].update(n_ctx=4096, source_tokens=128, output_tokens=256,
                                 startup_available_gib=args.startup_gib)
    atomic_json(job / 'working' / 'adapters.json', config)
    texts = ['你好，欢迎来到我们的频道。', '今天我们聊一聊怎样把中文翻译得更自然。',
             '外面下着大雨，只好等雨停了再走。', '请记住，安全比速度更重要。']
    source = [dict(start_ms=i*4000, end_ms=(i+1)*4000, text=text) for i, text in enumerate(texts)]
    (job / 'transcript.zh.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in source), encoding='utf-8')
    adapter = TranslationAdapter(config['translation']); adapter.job_dir = job
    began = time.monotonic()
    report = {'fixture': str(job), 'startup_gib': args.startup_gib, 'production_startup_unchanged': 3.5,
              'quick': args.quick, 'available_gib_before': round(psutil.virtual_memory().available/1024**3, 2)}
    try:
        translate(job, adapter)
        output = [json.loads(line) for line in (job/'transcript.vi.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [(r['start_ms'],r['end_ms'],r['text_zh']) for r in output] == [(r['start_ms'],r['end_ms'],r['text']) for r in source]
        assert export_translation_partial(job)['rows'] == len(source)
        translate(job, adapter)
        report.update(ok=True, translations=output, runtime=read_json(job/'working'/'translation-runtime.json'))
    except Exception as exc:
        report.update(ok=False, error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        adapter.close()
        report.update(seconds=round(time.monotonic()-began, 2), available_gib_after=round(psutil.virtual_memory().available/1024**3, 2))
        atomic_json(job/'report.json', report)
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
