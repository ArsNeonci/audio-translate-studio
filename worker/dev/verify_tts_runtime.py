"""Small real VieNeu CPU scaling and ordered WAV acceptance fixture."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import argparse
import json
import os
from pathlib import Path
import time
import psutil
import soundfile as sf
from audio_translate.tts.adapters import adapter_settings
from audio_translate.core.license_gate import assert_allowed
from audio_translate.workflow.postprocess import synthesize
from audio_translate.core.storage import ROOT,atomic_json,read_json
from audio_translate.tts.tts_runtime import Runtime,policy


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--quick',action='store_true')
    args=parser.parse_args();assert_allowed()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    job=ROOT/'data'/'verification'/('tts-workers-'+str(time.time_ns()))
    (job/'working').mkdir(parents=True)
    atomic_json(job/'job.json',dict(status='MODERATION_COMPLETED'))
    p=policy()
    if args.quick:p.update(threads=4,max_workers=2,cache_enabled=False)
    atomic_json(job/'policy.json',p);os.environ['TTS_RUNTIME_CONFIG']=str(job/'policy.json')
    config=adapter_settings(job)['tts']
    texts=['Xin chào, chúc bạn một ngày tốt lành.',
           'Hôm nay chúng ta cùng tìm hiểu cách xử lý âm thanh trên máy tính.',
           'Dù công việc có khó khăn, hãy bình tĩnh và thực hiện từng bước.',
           'Cảm ơn bạn đã lắng nghe. Hẹn gặp lại trong chương trình tiếp theo.']
    source=[dict(start_ms=i*4000,end_ms=(i+1)*4000,text_vi_moderated=t) for i,t in enumerate(texts)]
    (job/'transcript.vi.moderated.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in source),encoding='utf8')
    runtime=Runtime(job,config);began=time.monotonic()
    report=dict(fixture=str(job),quick=args.quick,config=config,available_gib_before=round(psutil.virtual_memory().available/1024**3,2))
    try:
        synthesize(job,runtime)
        manifest=[json.loads(l) for l in (job/'voice/voice.manifest.jsonl').read_text(encoding='utf8').splitlines()]
        assert [(r['start_ms'],r['end_ms'],r['text']) for r in manifest]==[(r['start_ms'],r['end_ms'],r['text_vi_moderated']) for r in source]
        wav=sf.info(str(job/'voice.vi.wav'))
        assert wav.frames==sum(sf.info(str(job/'voice'/r['file'])).frames for r in manifest)
        synthesize(job,runtime)  # completed-stage skip, no model restart
        report.update(ok=True,selected=runtime.selected,measurements=runtime.records,audio_seconds=wav.duration,
                      manifest_and_checkpoint_verified=True)
    except Exception as exc:
        report.update(ok=False,error=f'{type(exc).__name__}: {exc}');raise
    finally:
        runtime.close();report.update(seconds=round(time.monotonic()-began,2),available_gib_after=round(psutil.virtual_memory().available/1024**3,2))
        atomic_json(job/'report.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
