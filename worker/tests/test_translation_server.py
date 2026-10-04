import hashlib
import io
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio_translate.tts.adapters import adapter_settings, TranslationAdapter
from audio_translate.core.control import Cancelled
from audio_translate.workflow.postprocess import translate, export_translation_partial
from audio_translate.translation.translation_server import Runtime, SharedServer, DEFAULTS, slot_bytes, policy
from audio_translate.core.storage import atomic_json, read_json, Checkpoints
from tests.test_translation_runtime import Model


class FakeServer:
    capacity = 3
    threads = threads_batch = 4
    batch = 128
    def __init__(self, fail=None, pause=False, reason='eos', delays=None, misalign=False):
        self.fail, self.pause, self.reason, self.misalign = fail, pause, reason, misalign
        self.prompts = []
        self.calls = []; self.active = set(); self.lock = threading.Lock()
        self.peak = 0; self.overlap = False
        self.delays = delays or {}
        self.limit = None
        self.started = {}; self.finished = {}
        self.exceeded_after_reduction = False
        self.barrier = threading.Barrier(3) if pause else None
    def completion(self, prompt, slot, limit, progress, seed=42, temperature=.7):
        self.prompts.append(prompt)
        if '<source>' in prompt:
            rows = re.findall(r'<s(\d+)>(.*?)</s\1>', prompt.split('<source>')[-1])
            self.calls.append('GROUP:' + ''.join(text for _, text in rows))
            if self.misalign: return '<target>' + ''.join(text for _, text in rows) + '</target>', {'stop':True,'stop_type':'eos'}
            return '<target>' + ''.join(f'<s{i}>VI {hashlib.sha256(text.encode()).hexdigest()[:8]}</s{i}>' for i, text in rows) + '</target>', {'stop':True,'stop_type':'eos'}
        source = prompt.rsplit('\n\n', 1)[-1].split('<｜hy_Assistant｜>')[0]
        with self.lock:
            if self.limit and len(self.active) >= self.limit(): self.exceeded_after_reduction = True
            if slot in self.active: self.overlap = True
            self.active.add(slot); self.peak = max(self.peak, len(self.active)); self.calls.append(source)
            self.started[source] = time.monotonic()
        try:
            if self.barrier:
                self.barrier.wait(timeout=5)
                atomic_json(self.job/'working/cancel.signal', {'mode':'pause'})
            time.sleep(self.delays.get(source, .03 if source.startswith('甲') else .005))
            progress()
            if self.fail == source: raise RuntimeError('failed slot')
            return 'VI ' + hashlib.sha256(source.encode()).hexdigest()[:8], {'stop':True,'stop_type':self.reason}
        finally:
            with self.lock:
                self.active.remove(slot)
                self.finished[source] = time.monotonic()


class FakeRuntime:
    slots = 3
    def __init__(self, server): self.server = server
    def tune_between_batches(self, tasks): pass
    def observe(self): pass
    def close(self): pass


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name); (self.job/'working').mkdir()
        atomic_json(self.job/'job.json', {'status':'TRANSCRIPTION_COMPLETED'})
        self.config = adapter_settings(self.job)['translation']; self.config.update(source_tokens=16)
        settings = read_json(self.job/'working/adapters.json'); settings['translation'] = self.config
        atomic_json(self.job/'working/adapters.json', settings)
        for target, values in [('audio_translate.core.license_gate.assert_allowed',dict(return_value=True)),
                               ('psutil.virtual_memory',dict(return_value=SimpleNamespace(available=8*1024**3))),
                               ('psutil.sensors_battery',dict(return_value=None)),
                               ('psutil.cpu_percent',dict(return_value=0)),
                               ('audio_translate.core.memory_policy.commit_available',dict(return_value=None))]:
            p=patch(target,**values);p.start();self.addCleanup(p.stop)
    def adapter(self, **values):
        adapter=TranslationAdapter(self.config);adapter.model=Model();adapter.job_dir=self.job
        server=FakeServer(**values);server.job=self.job;adapter.runtime=FakeRuntime(server)
        return adapter,server
    def source(self, texts):
        values=[dict(start_ms=i*1000,end_ms=(i+1)*1000,text=t) for i,t in enumerate(texts)]
        (self.job/'transcript.zh.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in values),encoding='utf8')
        return values
    def test_out_of_order_parallel_outputs_keep_original_row_order_and_context(self):
        sources=self.source(['甲你好。','乙再见。','丙来了。','丁结束。'])
        adapter,server=self.adapter();translate(self.job,adapter)
        out=[json.loads(line) for line in (self.job/'transcript.vi.jsonl').read_text().splitlines()]
        self.assertEqual([(r['start_ms'],r['end_ms'],r['text_zh']) for r in out],[(r['start_ms'],r['end_ms'],r['text']) for r in sources])
        self.assertEqual([r['text_vi'] for r in out],['VI '+hashlib.sha256(r['text'].encode()).hexdigest()[:8] for r in sources])
        self.assertEqual(server.peak,3);self.assertFalse(server.overlap)
        self.assertEqual(len(server.calls),len(sources))

    def test_progress_updates_each_checkpointed_row_inside_a_window(self):
        texts=['甲慢一。','乙先完成。','丙慢二。'];self.source(texts)
        adapter,server=self.adapter(delays={texts[0]:.15,texts[2]:.1})
        from audio_translate.workflow.postprocess import progress
        with patch('audio_translate.workflow.postprocess.progress',wraps=progress) as update:
            translate(self.job,adapter)
        values=[call.args[3] for call in update.call_args_list if call.args[1]=='translation']
        self.assertIn(1,values);self.assertIn(2,values)
        self.assertEqual(values,sorted(values))
    def test_failed_slot_drains_other_valid_parts_and_resume_skips_them(self):
        texts=['甲你好。','乙再见。','丙来了。','丁结束。'];self.source(texts)
        adapter,server=self.adapter(fail=texts[1])
        with self.assertRaisesRegex(RuntimeError,'failed slot'):translate(self.job,adapter)
        self.assertEqual(export_translation_partial(self.job)['rows'],1)
        adapter,second=self.adapter();translate(self.job,adapter)
        self.assertNotIn(texts[0],second.calls);self.assertNotIn(texts[2],second.calls)
        self.assertIn(texts[1],second.calls)
    def test_pause_drains_all_current_slots_and_never_starts_pending_rows(self):
        self.source(['甲你好。','乙再见。','丙来了。','丁结束。'])
        adapter,server=self.adapter(pause=True)
        with self.assertRaises(Cancelled):translate(self.job,adapter)
        self.assertEqual(len(server.calls),3)
        self.assertEqual(export_translation_partial(self.job)['rows'],3)

    def test_memory_pressure_drains_and_checkpoints_before_releasing_model(self):
        self.source(['甲你好。','乙再见。','丙来了。','丁结束。'])
        adapter,server=self.adapter();runtime=adapter.runtime
        def observe(): runtime.admission_blocked=len(server.calls)>=3
        def tune(tasks):
            if getattr(runtime,'admission_blocked',False):
                self.assertFalse(server.active)
                raise Cancelled('memory reserve')
        runtime.observe=observe;runtime.tune_between_batches=tune
        with self.assertRaises(Cancelled):translate(self.job,adapter)
        self.assertEqual(len(server.calls),3)
        self.assertEqual(export_translation_partial(self.job)['rows'],3)
    def test_server_output_limit_never_checkpoints(self):
        self.source(['你好。']);adapter,server=self.adapter(reason='limit')
        with self.assertRaisesRegex(RuntimeError,'length budget'):translate(self.job,adapter)
        self.assertEqual(export_translation_partial(self.job)['rows'],0)
    def test_long_row_parts_remain_sequential_and_preserve_source(self):
        text='甲'*40+'。';self.source([text,'乙好了。','丙来了。'])
        adapter,server=self.adapter();translate(self.job,adapter)
        self.assertEqual(''.join(s for s in server.calls if s.startswith('甲') or s=='。'),text)
        self.assertFalse(server.overlap)

    def test_pressure_does_not_refill_idle_low_slot_while_high_slots_are_draining(self):
        texts=['乙先完成。','甲慢一。','丙慢二。','丁排队。'];self.source(texts)
        adapter,server=self.adapter(delays={texts[1]:.1,texts[2]:.1})
        runtime=adapter.runtime;server.limit=lambda:runtime.slots
        def reduce():runtime.slots=1
        runtime.observe=reduce
        translate(self.job,adapter)
        self.assertFalse(server.exceeded_after_reduction)
        self.assertEqual(export_translation_partial(self.job)['rows'],4)

    def test_idle_slot_refills_without_batch_barrier_but_read_ahead_is_bounded(self):
        texts=[f'段{i}。' for i in range(14)];self.source(texts)
        self.config['segmentation']='row'  # row-mode window; sentence mode reads ahead by groups
        adapter,server=self.adapter(delays={texts[0]:.25})
        from audio_translate.workflow.postprocess import atomic_json as write
        buffers=[]
        def telemetry(path,value):
            if Path(path).name=='translation-progress.json':buffers.append(value['buffered_rows'])
            return write(path,value)
        with patch('audio_translate.workflow.postprocess.atomic_json',side_effect=telemetry):translate(self.job,adapter)
        self.assertLess(server.started[texts[3]],server.finished[texts[0]])
        self.assertLess(server.started[texts[5]],server.finished[texts[0]])
        self.assertGreater(server.started[texts[6]],server.finished[texts[0]])
        self.assertLessEqual(max(buffers),6)
        self.assertEqual(export_translation_partial(self.job)['rows'],14)

    def test_prefix_is_visible_while_later_rows_are_still_running(self):
        texts=['首。','慢。','尾。','新。'];self.source(texts)
        adapter,server=self.adapter(delays={texts[1]:.2,texts[2]:.1})
        original=server.completion
        snapshots=[]
        def completion(prompt,*args,**kwargs):
            if prompt.endswith('\n\n'+texts[3]+'<｜hy_Assistant｜>'):
                snapshots.append((self.job/'transcript.vi.partial.jsonl').read_text(encoding='utf8'))
                self.assertFalse((self.job/'transcript.vi.jsonl').exists())
            return original(prompt,*args,**kwargs)
        server.completion=completion
        translate(self.job,adapter)
        self.assertEqual(len(snapshots),1)
        self.assertEqual([json.loads(line)['text_zh'] for line in snapshots[0].splitlines()],[texts[0]])

    def vi(self, text): return 'VI ' + hashlib.sha256(text.encode()).hexdigest()[:8]

    def test_sentence_rows_are_translated_together_and_split_back_to_their_timestamps(self):
        texts=['甲一，','乙二，','丙三。','丁四。'];sources=self.source(texts)
        adapter,server=self.adapter();translate(self.job,adapter)
        self.assertEqual(server.calls[0],'GROUP:甲一，乙二，丙三。')
        self.assertIn('丁四。',server.calls)  # a one-row sentence uses the row prompt
        out=[json.loads(line) for line in (self.job/'transcript.vi.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual([(r['start_ms'],r['end_ms'],r['text_zh'],r['text_vi']) for r in out],
                         [(r['start_ms'],r['end_ms'],r['text'],self.vi(r['text'])) for r in sources])
        progress=read_json(self.job/'working/translation-progress.json')
        self.assertEqual((progress['groups'],progress['grouped_rows'],progress['fallbacks']),(1,3,0))

    def test_unaligned_group_falls_back_to_row_by_row(self):
        texts=['甲一，','乙二。'];sources=self.source(texts)
        adapter,server=self.adapter(misalign=True);translate(self.job,adapter)
        self.assertEqual(server.calls,['GROUP:甲一，乙二。','GROUP:甲一，乙二。','甲一，','乙二。'])
        out=[json.loads(line)['text_vi'] for line in (self.job/'transcript.vi.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual(out,[self.vi(t) for t in texts])
        self.assertEqual(read_json(self.job/'working/translation-progress.json')['fallbacks'],1)

    def test_detected_names_are_saved_per_job_and_sent_as_terminology(self):
        texts=['张倩倩来了，','张倩倩笑了，','我和张倩倩说。','李强走了。'];self.source(texts)
        adapter,server=self.adapter();translate(self.job,adapter)
        names=read_json(self.job/'working/name-glossary.json')['names']
        self.assertEqual([(n['source'],n['target']) for n in names],[('张倩倩','Trương Thiến Thiến')])
        self.assertIn('参考下面的翻译：\n张倩倩 翻译成 Trương Thiến Thiến\n\n',server.prompts[0])
        self.assertNotIn('参考下面的翻译',server.prompts[-1])  # 李强 appears once: not detected
        # A user edit to the job glossary is used on the next run and changes row identities.
        atomic_json(self.job/'working/name-glossary.json',{'version':1,'names':[{'source':'李强','target':'Lý Cường'}]})
        (self.job/'working/translation.done.json').unlink()
        adapter,second=self.adapter();translate(self.job,adapter)
        self.assertTrue(any('李强 翻译成 Lý Cường' in p for p in second.prompts))

    def test_restored_progress_counts_valid_rows_after_a_gap(self):
        texts=['甲好。','乙坏。','丙好。'];self.source(texts)
        adapter,server=self.adapter(fail=texts[1])
        with self.assertRaises(RuntimeError):translate(self.job,adapter)
        adapter,server=self.adapter()
        from audio_translate.workflow.postprocess import progress
        with patch('audio_translate.workflow.postprocess.progress',wraps=progress) as update:translate(self.job,adapter)
        values=[call.args[3] for call in update.call_args_list]
        self.assertEqual(values[0],2)
        self.assertEqual(values,sorted(values))
        self.assertEqual(server.calls,[texts[1]])

    def test_continue_prioritizes_all_parts_of_failed_row_at_one_slot(self):
        text='甲'*40+'。';texts=[text,'乙好。','丙好。','丁新。','戊新。'];self.source(texts)
        adapter,server=self.adapter(fail='甲'*16)
        with self.assertRaises(RuntimeError):translate(self.job,adapter)
        atomic_json(self.job/'working/translation-continue.json',{'generation':1})
        adapter,server=self.adapter();translate(self.job,adapter)
        parts=list(adapter.parts(text))
        self.assertEqual(server.calls[:len(parts)],parts)
        self.assertNotIn(texts[1],server.calls);self.assertNotIn(texts[2],server.calls)
        self.assertEqual(server.peak,1)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.job=Path(self.temp.name);(self.job/'working').mkdir()
        self.policy={**DEFAULTS,'max_slots':0}
        self.path=self.job/'policy.json';atomic_json(self.path,self.policy)
        p=patch.dict('os.environ',HY_MT_RUNTIME_CONFIG=str(self.path));p.start();self.addCleanup(p.stop)
        self.config=dict(cpu_target=85,min_available_gib=1.5,n_ctx=4096,threads=4,n_batch=128)
        self.adapter=SimpleNamespace(settings=self.config,model=SimpleNamespace(metadata={}),job_dir=self.job)
        for target,values in [('psutil.cpu_percent',dict(return_value=0)),('psutil.cpu_count',dict(return_value=8)),
                              ('psutil.virtual_memory',dict(return_value=SimpleNamespace(available=8*1024**3))),
                              ('psutil.sensors_battery',dict(return_value=None)),('audio_translate.core.memory_policy.commit_available',dict(return_value=None))]:
            p=patch(target,**values);p.start();self.addCleanup(p.stop)
        self.runtime=Runtime(self.adapter)
        self.runtime.server=SimpleNamespace(capacity=1,threads=8,threads_batch=8,batch=256,close=lambda:None)
    def test_slot_budget_uses_model_kv_dimensions_not_asr_worker_formula(self):
        self.assertEqual(slot_bytes({},4096),384*1024**2)
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=int(1.8*1024**3))):
            self.assertFalse(self.runtime.can_expand(2))
        self.assertTrue(self.runtime.can_expand(8));self.assertFalse(self.runtime.can_expand(9))
    def test_commit_headroom_blocks_expansion(self):
        with patch('audio_translate.core.memory_policy.commit_available',return_value=1024**3):self.assertFalse(self.runtime.can_expand(2))

    def test_extra_slot_requires_two_gib_reserve_and_safety_margin(self):
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=int(2.7*1024**3))):
            self.assertFalse(self.runtime.can_expand(2))
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=int(2.8*1024**3))):
            self.assertTrue(self.runtime.can_expand(2))

    def test_vram_headroom_independently_blocks_gpu_expansion(self):
        self.config['device']='gpu'
        target='audio_translate.translation.translation_server.gpu_memory'
        with patch(target,return_value={'free':int(.8*1024**3),'total':8*1024**3,'name':'fixture'}):
            self.assertFalse(self.runtime.can_expand(2))
        with patch(target,return_value={'free':2*1024**3,'total':8*1024**3,'name':'fixture'}),patch('audio_translate.translation.translation_server.gpu_metrics',return_value={'utilization':20,'temperature':60}):
            self.assertTrue(self.runtime.can_expand(2))

    def test_one_slot_below_reserve_releases_model_and_pauses(self):
        self.adapter.close=lambda:None
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=int(1.9*1024**3))),patch.object(self.runtime.server,'close') as close:
            with self.assertRaises(Cancelled):self.runtime.tune_between_batches([])
            close.assert_called_once()
        self.assertEqual(read_json(self.job/'working/translation-runtime.json')['state'],'WAITING_MEMORY')

    def test_recovery_requires_thirty_seconds_after_pressure(self):
        self.runtime.last_observed=0
        with patch('audio_translate.translation.translation_server.time.monotonic',return_value=100),patch('psutil.cpu_percent',return_value=95):
            self.runtime.observe()
        self.assertEqual(self.runtime.recover_after,130)
    def test_battery_cpu_target_prevents_expansion(self):
        with patch('psutil.sensors_battery',return_value=SimpleNamespace(power_plugged=False)),patch('psutil.cpu_percent',return_value=70):
            self.assertFalse(self.runtime.can_expand(2))
    def test_pressure_reduces_slots_and_defers_thread_restart_until_drained(self):
        self.runtime.slots=4;self.runtime.last_observed=0
        with patch('psutil.cpu_percent',return_value=95):self.runtime.observe()
        self.assertEqual(self.runtime.slots,2);self.assertEqual(self.runtime.pending_reduction,4)
        self.assertEqual(self.runtime.server.threads,8)
        with patch.object(self.runtime,'start') as start:self.runtime.tune_between_batches([])
        start.assert_called_once_with(4,4,256,2)
    def test_live_max_slots_change_applies_at_drained_boundary(self):
        self.runtime.slots=4;self.policy['max_slots']=1;atomic_json(self.path,self.policy)
        with patch.object(self.runtime,'start') as start:self.runtime.tune_between_batches([])
        self.assertEqual(start.call_args.args[-1],1);self.assertEqual(self.runtime.slots,1)
    def test_invalid_live_configuration_is_rejected(self):
        for key,value in [('threads',-1),('reserve_gib',float('nan')),('max_slots',True)]:
            atomic_json(self.path,{**self.policy,key:value})
            with self.assertRaises(ValueError):policy()

    def test_stable_resources_expand_without_synthetic_completions(self):
        self.runtime.healthy_since=0
        self.runtime.server.threads=4;self.runtime.server.batch=128
        tasks=[(i,0,'text','') for i in range(8)]
        with patch('audio_translate.translation.translation_server.time.monotonic',return_value=11),patch.object(self.runtime,'start') as start:
            self.runtime.tune_between_batches(tasks)
        start.assert_called_once_with(4,4,128,2)
        self.assertEqual(self.runtime.slots,2)
        self.assertFalse(hasattr(self.runtime,'measure'))
        self.assertFalse(hasattr(self.runtime,'calibrate'))

    def test_expansion_waits_for_stable_resources_without_delaying_translation(self):
        self.runtime.healthy_since=5
        self.runtime.server.threads=4;self.runtime.server.batch=128
        self.runtime.server.threads_batch=4
        with patch('audio_translate.translation.translation_server.time.monotonic',return_value=11),patch.object(self.runtime,'start') as start:
            self.runtime.tune_between_batches([(i,0,'text','') for i in range(8)])
        start.assert_not_called()
        self.assertEqual(self.runtime.slots,1)

    def test_thermal_pressure_prevents_expansion(self):
        sensor=SimpleNamespace(current=90)
        with patch('psutil.sensors_temperatures',create=True,return_value={'cpu':[sensor]}):
            self.assertFalse(self.runtime.can_expand(2))

    def test_resource_admission_can_expand_beyond_four_slots(self):
        self.runtime.slots=4;self.runtime.server.capacity=4
        self.runtime.server.threads=4;self.runtime.server.batch=128
        self.runtime.healthy_since=0
        with patch('audio_translate.translation.translation_server.time.monotonic',return_value=11),patch.object(self.runtime,'start') as start:
            self.runtime.tune_between_batches([(i,0,'text','') for i in range(16)])
        self.assertEqual(start.call_args.args[-1],5)
        self.assertEqual(self.runtime.slots,5)

    def test_gpu_utilization_and_temperature_block_expansion(self):
        self.config['device']='gpu'
        with (patch('audio_translate.translation.translation_server.gpu_memory',return_value={'free':4*1024**3,'total':8*1024**3,'name':'fixture'}),
              patch('audio_translate.translation.translation_server.gpu_metrics',return_value={'utilization':85,'temperature':60})):
            self.assertFalse(self.runtime.can_expand(2))
        with (patch('audio_translate.translation.translation_server.gpu_memory',return_value={'free':4*1024**3,'total':8*1024**3,'name':'fixture'}),
              patch('audio_translate.translation.translation_server.gpu_metrics',return_value={'utilization':20,'temperature':85})):
            self.assertFalse(self.runtime.can_expand(2))

    def test_critical_ram_pauses_and_releases_helper(self):
        self.runtime.last_observed=0
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=100*1024**2)),patch.object(self.runtime.server,'close') as close:
            with self.assertRaises(Cancelled):self.runtime.observe()
            close.assert_called_once()
        self.assertEqual(read_json(self.job/'working/cancel.signal')['mode'],'pause')


class TransportTests(unittest.TestCase):
    def test_sse_comments_and_final_metadata_preserve_cached_slot_request(self):
        server=SharedServer({},None,4,4,128,2)
        response=io.BytesIO(b': ping\n\ndata: {"content":"Xin ","stop":false}\n\ndata: {"content":"chao","stop":false}\n\ndata: {"content":"","stop":true,"stop_type":"eos","tokens_predicted":2}\n\n')
        ticks=[]
        with patch.object(server,'request',return_value=response) as request:
            result,final=server.completion('prompt',1,64,lambda:ticks.append(1))
        self.assertEqual(result,'Xin chao');self.assertEqual(final['stop_type'],'eos')
        self.assertEqual(request.call_args.args[1]['id_slot'],1)
        self.assertTrue(request.call_args.args[1]['cache_prompt']);self.assertTrue(ticks)
    def test_disconnected_stream_does_not_return_partial_translation(self):
        server=SharedServer({},None,4,4,128,1)
        with patch.object(server,'request',return_value=io.BytesIO(b'data: {"content":"partial","stop":false}\n\n')):
            with self.assertRaisesRegex(RuntimeError,'completion marker'):server.completion('prompt',0,64)


if __name__=='__main__':unittest.main()
