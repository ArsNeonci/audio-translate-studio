"""Measure real CPU translation slots without changing runtime policy or jobs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
from llama_cpp import Llama
from audio_translate.core.license_gate import assert_allowed
from audio_translate.core.storage import ROOT, atomic_json
from audio_translate.translation.hymt_translation import TranslationAdapter, default_settings
from audio_translate.translation.translation_server import SharedServer

GIB = 1024 ** 3
SOURCES = [
    '今天我们去参观了一家小型工厂。负责人告诉我们，他们以前只重视生产速度，后来发现产品质量更重要。现在每件产品出厂前都要经过检查。如果发现问题，工人会立即记录下来，并和工程师一起寻找原因。这样虽然花费了更多时间，却减少了客户投诉。',
    '我本来打算一早出门，没想到外面突然下起了大雨。妈妈让我带上雨伞，再穿一件外套。我等了半个小时，雨还是没有停，只好坐公交车去公司。到达办公室的时候，同事已经准备好了会议资料，大家正在讨论下个月的工作计划。',
    '这个村子离城市很远，但交通比以前方便多了。过去孩子们每天要走很长的路去上学，现在有了校车。老人也可以在附近的卫生站看病，不用每次都去县城。村民说，他们最希望的是年轻人能够回来工作，让家乡变得更有活力。',
    '学习一门语言不能只背单词，还要理解不同场景下的表达方式。同一句话，在朋友之间可以说得轻松一些，在正式会议上则需要更加礼貌。翻译的时候，我们应该保留原文的意思，同时让目标语言的读者觉得自然，而不是机械地照搬句子结构。',
    '张老师昨天提醒我们，做实验之前必须检查设备，并仔细阅读操作说明。如果遇到不熟悉的步骤，应该先请教老师，不要随意尝试。实验结束后，还要整理桌面，把工具放回原来的位置。安全和准确都很重要，不能为了节省几分钟而忽略这些要求。',
    '周末我和朋友一起做了一顿晚饭。我们先去市场买了蔬菜、鱼和一些水果，然后分工准备食材。虽然厨房不大，大家却配合得很好。吃饭的时候，我们聊起了小时候的经历，也讨论了未来的打算。那天没有特别昂贵的菜，却让人觉得很温暖。',
]


def main():
    assert_allowed()
    directory = ROOT / 'data' / 'verification' / ('hymt-memory-' + str(time.time_ns()))
    directory.mkdir(parents=True)
    settings = default_settings()
    settings.update(device='cpu', n_gpu_layers=0)
    adapter = TranslationAdapter(settings)
    adapter.model = Llama(model_path=settings['model'], vocab_only=True, verbose=False)
    prompts = [adapter.prompt(source, '') for source in SOURCES]
    report = dict(model=Path(settings['model']).name, context_per_slot=settings['n_ctx'],
                  source_tokens=settings['source_tokens'], output_tokens=settings['output_tokens'],
                  threads=settings['threads'], n_batch=settings['n_batch'],
                  total_ram_gib=round(psutil.virtual_memory().total / GIB, 3),
                  workload_rows=len(SOURCES), sample_interval_seconds=.05,
                  meaning='1x/2x/3x are concurrent slots sharing one loaded model', cases=[])
    try:
        for count in (1, 2, 3):
            case_dir = directory / str(count)
            server = SharedServer(settings, case_dir, settings['threads'], settings['threads'], settings['n_batch'], count)
            samples = []; stop = threading.Event()
            baseline = psutil.virtual_memory().available
            def sample():
                while not stop.wait(.05):
                    try:
                        info = psutil.Process(server.process.pid).memory_info() if server.process else None
                        samples.append((time.monotonic(), info.rss if info else 0,
                                        getattr(info, 'private', 0) if info else 0,
                                        psutil.Process().memory_info().rss,
                                        psutil.virtual_memory().available))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            thread = threading.Thread(target=sample, daemon=True); thread.start()
            began = time.monotonic()
            try:
                server.start()
                loaded = psutil.Process(server.process.pid).memory_info()
                loading_seconds = time.monotonic() - began
                began_inference = time.monotonic(); outputs = []; tokens = 0
                with ThreadPoolExecutor(max_workers=count) as pool:
                    for offset in range(0, len(prompts), count):
                        futures = [pool.submit(server.completion, prompt, slot, settings['output_tokens'])
                                   for slot, prompt in enumerate(prompts[offset:offset+count])]
                        for future in futures:
                            text, metadata = future.result()
                            if not text.strip() or metadata.get('stop_type') not in ('eos', 'word') or metadata.get('truncated') or metadata.get('stopped_limit'):
                                raise RuntimeError('Benchmark translation did not complete')
                            tokens += metadata.get('tokens_predicted', 0)
                            outputs.append(text)
                seconds = time.monotonic() - began_inference
                time.sleep(.15)
                inference = [s for s in samples if s[0] >= began_inference]
                case = dict(slots=count, completed_rows=len(outputs), load_seconds=round(loading_seconds, 2),
                            inference_seconds=round(seconds, 2), predicted_tokens=tokens,
                            tokens_per_second=round(tokens / seconds, 2),
                            loaded_server_rss_gib=round(loaded.rss/GIB, 3),
                            peak_server_rss_gib=round(max(s[1] for s in samples)/GIB, 3),
                            peak_server_private_gib=round(max(s[2] for s in samples)/GIB, 3),
                            peak_worker_rss_gib=round(max(s[3] for s in samples)/GIB, 3),
                            peak_combined_rss_gib=round(max(s[1]+s[3] for s in samples)/GIB, 3),
                            available_before_gib=round(baseline/GIB, 3),
                            minimum_available_gib=round(min(s[4] for s in samples)/GIB, 3),
                            inference_minimum_available_gib=round(min(s[4] for s in inference)/GIB, 3),
                            outputs=outputs)
                report['cases'].append(case)
                atomic_json(directory / 'report.json', report)
                print(json.dumps({k:v for k,v in case.items() if k!='outputs'}), flush=True)
            finally:
                stop.set(); thread.join(timeout=2); server.close()
    finally:
        adapter.close()
        atomic_json(directory / 'report.json', report)
    print('REPORT: ' + str(directory / 'report.json'), flush=True)


if __name__ == '__main__':
    main()
