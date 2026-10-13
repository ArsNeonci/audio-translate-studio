"""Validate actual GGUF tokenization without loading inference tensors."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import argparse,json,time
from pathlib import Path
from llama_cpp import Llama
from audio_translate.tts.adapters import TranslationAdapter,adapter_settings
from audio_translate.core.storage import ROOT,atomic_json

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',type=Path,required=True);args=parser.parse_args()
    config=adapter_settings(args.job)['translation'];adapter=TranslationAdapter(config)
    began=time.monotonic();results=[]
    model=Llama(model_path=config['model'],vocab_only=True,verbose=False)
    try:
        adapter.model=model
        for text in ['你好。今天我们学习中文！明天继续？'*200,'这是一个没有标点的很长的中文文本'*200,'他说：“张三来了。”价格是3.14元。'*200]:
            parts=list(adapter.parts(text));counts=[adapter.token_count(part) for part in parts]
            assert ''.join(parts)==text and max(counts)<=config['source_tokens']
            results.append({'characters':len(text),'parts':len(parts),'maximum_tokens':max(counts),'source_preserved':True})
    finally:
        model.close()
    report={'kind':'actual_hymt_gguf_tokenizer_no_inference','cases':results,'seconds':round(time.monotonic()-began,3)}
    atomic_json(ROOT/'data/verification/translation-long/tokenizer-result.json',report);print(json.dumps(report))

if __name__=='__main__':main()
