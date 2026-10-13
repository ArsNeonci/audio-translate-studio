"""Synthetic coordinator/checkpoint scaling; does not execute a translation model."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import argparse
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch
import uuid

import psutil
from audio_translate.tts.adapters import adapter_settings
from audio_translate.workflow.postprocess import translate,export_translation_partial
from audio_translate.core.storage import ROOT,atomic_json,rows


class SyntheticTranslator:
    def __init__(self):self.maximum_rows_in_call=0
    def translate_checkpointed(self,texts,lookup,save,save_row,contexts=None):
        self.maximum_rows_in_call=max(self.maximum_rows_in_call,len(texts))
        results=[]
        for owner,text in enumerate(texts):
            parts=text.split('|')
            output=[]
            for part_id,source in enumerate(parts):
                value=lookup(owner,part_id,source)
                if value is None:
                    value='synthetic '+source
                    save(owner,part_id,source,value)
                output.append(value)
            value=' '.join(output);save_row(owner,value);results.append(value)
        return results


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--counts',type=int,nargs=3,default=[1000,6000,12000])
    args=parser.parse_args()
    destination=ROOT/'data/verification/translation-long'/('streaming-'+uuid.uuid4().hex)
    destination.mkdir(parents=True)
    report={'kind':'synthetic_coordinator_only_no_model_inference','cases':[]}
    process=psutil.Process()
    for hours,count in zip((1,6,60),args.counts):
        if count<1:raise ValueError('counts must be positive')
        job=destination/f'{hours}h';(job/'working').mkdir(parents=True)
        atomic_json(job/'job.json',{'status':'TRANSCRIPTION_COMPLETED'})
        config=adapter_settings(job);config['translation']['batch_size']=4
        atomic_json(job/'working/adapters.json',config)
        duration=hours*3600000
        with (job/'transcript.zh.jsonl').open('w',encoding='utf-8') as handle:
            for index in range(count):
                handle.write(json.dumps({'start_ms':index*duration//count,'end_ms':(index+1)*duration//count,
                    'text':f'句子{index}。|后续内容。'},ensure_ascii=False)+'\n')
        baseline=process.memory_info().rss;peaks=[baseline];stop=threading.Event()
        def sample():
            while not stop.wait(.05):peaks[0]=max(peaks[0],process.memory_info().rss)
        sampler=threading.Thread(target=sample,daemon=True);sampler.start()
        began=time.monotonic();adapter=SyntheticTranslator()
        # Test fixture only: no protected model execution, downloads or user jobs.
        try:
            with patch('audio_translate.core.license_gate.assert_allowed',return_value=True):translate(job,adapter)
        finally:stop.set();sampler.join()
        seconds=time.monotonic()-began
        exported=export_translation_partial(job)
        visited=0
        for index,row in rows(job/'transcript.vi.jsonl','text_vi'):
            assert row['start_ms']==(index-1)*duration//count and row['end_ms']==index*duration//count
            visited+=1
        assert visited==count and exported['rows']==count and adapter.maximum_rows_in_call<=4
        item={'span_hours':hours,'rows':count,'seconds':round(seconds,3),'maximum_rows_in_call':adapter.maximum_rows_in_call,
              'peak_rss_mib':round(peaks[0]/1024**2,2),'rss_increase_mib':round((peaks[0]-baseline)/1024**2,2),
              'timestamps_and_count_verified':True,'partial_export_rows':exported['rows']}
        report['cases'].append(item);atomic_json(destination/'report.json',report)
        print(json.dumps(item),flush=True)
    print('REPORT '+str(destination/'report.json'),flush=True)


if __name__=='__main__':main()
