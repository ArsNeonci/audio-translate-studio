import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
from audio_translate.tts.adapters import adapter_settings
from audio_translate.core.control import Cancelled
from audio_translate.workflow.postprocess import synthesize
from audio_translate.core.storage import atomic_json,read_json,file_digest
from audio_translate.tts.tts_runtime import Runtime,ContentCache,DEFAULTS,policy


class TTSTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.job=self.root/'job';(self.job/'working').mkdir(parents=True)
        atomic_json(self.job/'job.json',dict(status='MODERATION_COMPLETED'))
        self.config=adapter_settings(self.job)['tts']
        self.values={**DEFAULTS,'calibrate':False,'cache_enabled':False,'max_workers':3}
        self.path=self.root/'policy.json';atomic_json(self.path,self.values)
        self.h=dict(available=16*1024**3,commit=16*1024**3,cpu=0,target=85,cores=8,hot=False)
        for p in (patch.dict('os.environ',TTS_RUNTIME_CONFIG=str(self.path)),patch('audio_translate.tts.tts_runtime.DATA',self.root),
                  patch('audio_translate.tts.tts_runtime.hardware',side_effect=lambda:self.h.copy()),patch('audio_translate.core.license_gate.assert_allowed',return_value=True)):
            p.start();self.addCleanup(p.stop)
    def source(self,texts,job=None):
        job=job or self.job
        rows=[dict(start_ms=i*1000,end_ms=(i+1)*1000,text_vi_moderated=t) for i,t in enumerate(texts)]
        (job/'transcript.vi.moderated.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8')
        return rows
    def runtime(self,count=3):
        runtime=Runtime(self.job,self.config,fake=True);self.addCleanup(runtime.close)
        runtime.configure(count,1);runtime.selected=dict(workers=count,threads=1);return runtime
    def test_parallel_wavs_manifest_keep_source_order_and_timestamps(self):
        source=self.source(['SLOW first','second','third','fourth'])
        runtime=self.runtime();synthesize(self.job,runtime)
        out=[json.loads(l) for l in (self.job/'voice/voice.manifest.jsonl').read_text().splitlines()]
        self.assertEqual([(r['start_ms'],r['end_ms'],r['text']) for r in out],[(r['start_ms'],r['end_ms'],r['text_vi_moderated']) for r in source])
        self.assertEqual(sf.info(str(self.job/'voice.vi.wav')).frames,4*480)
        self.assertFalse(runtime.pool.members)
    def test_failure_drains_other_workers_and_resume_reuses_valid_wavs(self):
        self.source(['SLOW first','FAIL second','third'])
        with self.assertRaisesRegex(RuntimeError,'simulated TTS'):synthesize(self.job,self.runtime())
        first=self.job/'voice/000001.wav';third=self.job/'voice/000003.wav'
        self.assertTrue(first.exists());self.assertTrue(third.exists())
        before=(file_digest(first),first.stat().st_mtime_ns)
        self.source(['SLOW first','fixed second','third'])
        synthesize(self.job,self.runtime())
        self.assertEqual((file_digest(first),first.stat().st_mtime_ns),before)
    def test_pause_drains_current_workers_and_skips_queued_rows(self):
        self.source(['PAUSE first','SLOW second','SLOW third','queued'])
        with self.assertRaises(Cancelled):synthesize(self.job,self.runtime())
        self.assertEqual(len(list((self.job/'voice').glob('*.wav'))),3)
        self.assertFalse((self.job/'voice/000004.wav').exists())
        (self.job/'working/cancel.signal').unlink()
        synthesize(self.job,self.runtime())
        self.assertEqual(sf.info(str(self.job/'voice.vi.wav')).frames,4*480)
    def test_cache_reuses_identical_text_across_rows_and_jobs_without_workers(self):
        self.values['cache_enabled']=True;atomic_json(self.path,self.values)
        self.source(['same','same']);runtime=self.runtime();synthesize(self.job,runtime)
        first=self.job/'voice/000001.wav';self.assertEqual(file_digest(first),file_digest(self.job/'voice/000002.wav'))
        second=self.root/'second';(second/'working').mkdir(parents=True)
        atomic_json(second/'job.json',dict(status='MODERATION_COMPLETED'));adapter_settings(second)
        self.source(['same'],second)
        runtime=Runtime(second,self.config,fake=True)
        with patch.object(runtime,'prepare',side_effect=AssertionError('cache hit must skip model load')):
            synthesize(second,runtime)
        self.assertEqual(runtime.cache_hits,1)
    def test_cache_voice_and_corruption_cannot_reuse_wrong_audio(self):
        self.values['cache_enabled']=True;atomic_json(self.path,self.values)
        cache=ContentCache(self.config,'fake');wav=self.root/'input.wav'
        sf.write(wav,np.ones(480)*.05,48000,subtype='PCM_16');cache.put('text',wav)
        changed=ContentCache({**self.config,'voice':'different'},'fake')
        self.assertFalse(changed.get('text',self.root/'result.wav'))
        target=cache.directory/(cache.key('text')+'.wav');target.write_bytes(b'broken')
        self.assertFalse(cache.get('text',self.root/'result.wav'))
    def test_memory_wait_pauses_before_loading_and_preserves_checkpoints(self):
        runtime=Runtime(self.job,self.config,fake=True)
        self.h['available']=1024**3;self.values['memory_wait_seconds']=.001;atomic_json(self.path,self.values)
        with self.assertRaises(Cancelled):runtime.add(4,initial=True)
        self.assertEqual(read_json(self.job/'working/cancel.signal')['mode'],'pause')
        self.assertFalse(runtime.pool.members)
    def test_cpu_commit_thermal_and_worker_limits_block_growth(self):
        runtime=Runtime(self.job,self.config,fake=True)
        self.assertTrue(runtime.fit(3));self.assertFalse(runtime.fit(4))
        for key,value in [('cpu',90),('hot',True),('commit',1024**3),('available',1024**3)]:
            old=self.h[key];self.h[key]=value;self.assertFalse(runtime.fit(2));self.h[key]=old
    def test_live_invalid_config_rejected(self):
        for key,value in [('threads',-1),('cpu_target',101),('max_workers',True),('reserve_gib',float('nan'))]:
            atomic_json(self.path,{**self.values,key:value})
            with self.assertRaises(ValueError):policy()

    def test_cancel_releases_workers_before_removing_open_temporary_wavs(self):
        self.source(['SLOW first','SLOW second','SLOW third'])
        runtime=self.runtime()
        timer=threading.Timer(.05,lambda:atomic_json(self.job/'working/cancel.signal',dict(mode='cancel')))
        timer.start();self.addCleanup(timer.join)
        with self.assertRaises(Cancelled):synthesize(self.job,runtime)
        self.assertFalse(runtime.pool.members)
        self.assertFalse(list((self.job/'voice').glob('*.tmp')))
        self.assertFalse(list((self.job/'voice').glob('*.wav')))

    def test_calibration_selects_gain_and_reuses_hardware_profile(self):
        self.values.update(calibrate=True,max_workers=4);atomic_json(self.path,self.values)
        runtime=Runtime(self.job,self.config,fake=True)
        def configure(count,threads):
            runtime.pool.members=[dict(threads=threads) for _ in range(count)];return True
        def measure(texts,count,threads):
            seconds=({4:100,6:90,8:70}[threads] if count==1 else {2:50,4:47}[count])
            value=dict(workers=count,threads=threads,seconds=seconds,rtf=.5)
            runtime.records.append(value);return value
        with patch.object(runtime,'configure',side_effect=configure),patch.object(runtime,'measure',side_effect=measure):
            runtime.prepare(['short','medium text','long text','another text'])
            self.assertEqual((runtime.selected['workers'],runtime.selected['threads']),(2,4))
            runtime.selected=None
            with patch.object(runtime,'measure',side_effect=AssertionError('profile must skip calibration')):
                runtime.prepare(['short','medium text'])
            self.assertEqual((runtime.selected['workers'],runtime.selected['threads']),(2,4))
        runtime.pool.members=[]

    def test_cache_eviction_enforces_entry_limit(self):
        self.values.update(cache_enabled=True,cache_max_entries=1);atomic_json(self.path,self.values)
        cache=ContentCache(self.config,'fake');wav=self.root/'input.wav'
        sf.write(wav,np.ones(480)*.05,48000,subtype='PCM_16')
        cache.put('one',wav);cache.put('two',wav);cache.trim()
        self.assertEqual(len(list(cache.directory.glob('*.json'))),1)
        self.assertTrue(cache.get('two',self.root/'copy.wav'))

    def test_explicit_reprocess_generates_fresh_audio_even_when_content_cache_exists(self):
        self.values['cache_enabled']=True;atomic_json(self.path,self.values)
        self.source(['same'])
        wav=self.root/'cached.wav';sf.write(wav,np.ones(480)*.05,48000,subtype='PCM_16')
        ContentCache(self.config,'fake').put('same',wav)
        atomic_json(self.job/'job.json',dict(status='MODERATION_COMPLETED',reprocess_pending=True))
        runtime=self.runtime(count=1)
        with patch.object(runtime,'run',wraps=runtime.run) as run:synthesize(self.job,runtime)
        run.assert_called_once();self.assertEqual(runtime.cache_hits,0)

    def test_empty_moderated_rows_keep_minimal_wavs_without_loading_a_model(self):
        self.source(['','   ']);runtime=Runtime(self.job,self.config,fake=True)
        with patch.object(runtime,'prepare',side_effect=AssertionError('empty rows must skip model')):
            synthesize(self.job,runtime)
        self.assertEqual(sf.info(str(self.job/'voice.vi.wav')).frames,2)
        self.assertFalse(runtime.pool.members)


if __name__=='__main__':unittest.main()
