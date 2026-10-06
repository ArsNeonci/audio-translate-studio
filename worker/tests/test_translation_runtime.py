import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from audio_translate.tts.adapters import TranslationAdapter,adapter_settings
from audio_translate.workflow.postprocess import translate,export_translation_partial,apply_glossary
from audio_translate.core.storage import atomic_json,Checkpoints,read_json
from audio_translate.translation.hymt_translation import ASSISTANT,STRATEGIES,attempt_seed,output_problem,TranslationFailure

class Model:
    ctx=None
    def __init__(self,fail_after=None,reason='stop',response=None):
        self.calls=[];self.fail_after=fail_after;self.reason=reason;self.response=response
    def tokenize(self,data,**kwargs):return list(data.decode('utf-8'))
    def create_completion(self,prompt,**kwargs):
        if self.fail_after is not None and len(self.calls)>=self.fail_after:raise RuntimeError('simulated interruption')
        self.calls.append(prompt)
        self.kwargs=kwargs
        source=prompt.rsplit('\n\n',1)[-1].split('<｜hy_Assistant｜>')[0]
        yield {'choices':[{'text':self.response if self.response is not None else 'B?n d?ch '+hashlib.sha256(source.encode()).hexdigest()[:8],'finish_reason':None}]}
        yield {'choices':[{'text':'','finish_reason':self.reason}]}

class TranslationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.job=Path(self.temp.name);(self.job/'working').mkdir()
        atomic_json(self.job/'job.json',{'status':'TRANSCRIPTION_COMPLETED'})
        settings=adapter_settings(self.job);settings['translation'].update(batch_size=4,source_tokens=16)
        atomic_json(self.job/'working/adapters.json',settings);self.config=settings['translation']
        for target,kwargs in (
            ('audio_translate.core.license_gate.assert_allowed',{'return_value':True}),
            ('psutil.cpu_percent',{'return_value':0}),
            ('psutil.sensors_battery',{'return_value':None}),
            ('psutil.virtual_memory',{'return_value':SimpleNamespace(available=8*1024**3)}),
            ('audio_translate.core.memory_policy.commit_available',{'return_value':None}),
            ('llama_cpp.llama_set_n_threads',{})):
            mocked=patch(target,**kwargs);mocked.start();self.addCleanup(mocked.stop)
    def adapter(self,**kwargs):
        adapter=TranslationAdapter(self.config);adapter.model=Model(**kwargs);return adapter
    def source(self,texts):
        source=[{'text':text,'start_ms':i*216000000//len(texts),'end_ms':(i+1)*216000000//len(texts)} for i,text in enumerate(texts)]
        (self.job/'transcript.zh.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in source),encoding='utf-8');return source
    def test_adjacent_sentences_kept_together_and_long_source_lossless(self):
        adapter=self.adapter();self.assertEqual(list(adapter.parts('你好。今天很好！')),['你好。今天很好！'])
        for text in ('你好。今天很好！再见？','甲'*1000,'数值3.14很好。 abc def ghi, jkl mno pqr stu.'):
            parts=list(adapter.parts(text));self.assertEqual(''.join(parts),text)
            self.assertTrue(all(adapter.token_count(part)<=16 for part in parts))
    def test_order_and_non_thinking_prompt(self):
        adapter=self.adapter();texts=['你好。','再见。']
        self.assertEqual(adapter.translate(texts),['B?n d?ch '+hashlib.sha256(text.encode()).hexdigest()[:8] for text in texts])
        self.assertTrue(all(prompt.startswith('<｜hy_begin▁of▁sentence｜><｜hy_User｜>') and prompt.endswith('<｜hy_Assistant｜>') and '<think>' not in prompt for prompt in adapter.model.calls))
    def test_resume_with_context_and_partial_export_preserves_timestamps(self):
        source=self.source(['你好。','甲'*30+'。']);adapter=self.adapter(fail_after=2)
        with self.assertRaisesRegex(RuntimeError,'simulated interruption'):translate(self.job,adapter)
        self.assertEqual(export_translation_partial(self.job)['rows'],1)
        resumed=self.adapter();translate(self.job,resumed)
        output=[json.loads(line) for line in (self.job/'transcript.vi.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([(r['start_ms'],r['end_ms'],r['text_zh']) for r in output],[(r['start_ms'],r['end_ms'],r['text']) for r in source])
        self.assertTrue(set(adapter.model.calls).isdisjoint(resumed.model.calls))
        self.assertEqual(export_translation_partial(self.job)['rows'],2)
    def test_context_spans_batches_and_resume(self):
        settings=read_json(self.job/'working/adapters.json');settings['translation']['batch_size']=1
        atomic_json(self.job/'working/adapters.json',settings);self.source(['张三是老师。','他来了。'])
        with self.assertRaises(RuntimeError):translate(self.job,self.adapter(fail_after=1))
        resumed=self.adapter();translate(self.job,resumed)
        # Background is no longer sent: it made the model translate the context instead.
        self.assertNotIn('张三是老师',resumed.model.calls[0])
        self.assertTrue(resumed.model.calls[0].endswith('\n\n他来了。'+ASSISTANT))
    def test_truncated_empty_and_reasoning_outputs_never_checkpointed(self):
        self.source(['你好。'])
        for kwargs in ({'reason':'length'},{'response':''},{'response':'<think>analysis</think>text'}):
            with self.assertRaises(RuntimeError):translate(self.job,self.adapter(**kwargs))
            self.assertEqual(export_translation_partial(self.job)['rows'],0)
        translate(self.job,self.adapter());self.assertEqual(export_translation_partial(self.job)['rows'],1)
    def test_low_ram_pauses_and_retains_parts(self):
        adapter=self.adapter();adapter.job_dir=self.job
        with Checkpoints(self.job) as db:db.put_translation_part(1,0,'saved','VI saved')
        self.config['memory_wait_seconds']=.001
        from audio_translate.core.control import Cancelled
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=100*1024**2)),patch('audio_translate.translation.hymt_translation.time.monotonic',side_effect=[0,1]),self.assertRaises(Cancelled):adapter.wait_memory(.5,'INFERENCE')
        self.assertEqual(read_json(self.job/'working/cancel.signal')['mode'],'pause')
        with Checkpoints(self.job) as db:self.assertEqual(db.get_translation_part(1,0,'saved'),'VI saved')

    def test_cpu_startup_accepts_exactly_three_point_five_gib(self):
        adapter=self.adapter()
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=int(3.5*1024**3))),patch('audio_translate.core.memory_policy.commit_available',return_value=int(3.5*1024**3)):
            adapter.wait_memory(3.5,'MODEL_LOADING')

    def test_commit_limit_blocks_startup_despite_available_ram(self):
        adapter=self.adapter();adapter.job_dir=self.job;self.config['memory_wait_seconds']=.001
        from audio_translate.core.control import Cancelled
        with patch('audio_translate.core.memory_policy.commit_available',return_value=3*1024**3),patch('audio_translate.translation.hymt_translation.time.monotonic',side_effect=[0,1]):
            with self.assertRaises(Cancelled):adapter.wait_memory(3.5,'MODEL_LOADING')
    def test_abort_during_generation_discards_unsaved_part(self):
        self.source(['你好。']);adapter=self.adapter();original=adapter.model.create_completion
        def abort(*args,**kwargs):
            for chunk in original(*args,**kwargs):
                atomic_json(self.job/'working/cancel.signal',{'mode':'cancel'});yield chunk
        adapter.model.create_completion=abort
        from audio_translate.core.control import Cancelled
        with self.assertRaises(Cancelled):translate(self.job,adapter)
        self.assertEqual(export_translation_partial(self.job)['rows'],0)
    def test_pause_drains_and_saves_current_part(self):
        self.source(['你好。','再见。']);adapter=self.adapter();original=adapter.model.create_completion
        def pause(*args,**kwargs):
            for chunk in original(*args,**kwargs):
                atomic_json(self.job/'working/cancel.signal',{'mode':'pause'});yield chunk
        adapter.model.create_completion=pause
        from audio_translate.core.control import Cancelled
        with self.assertRaises(Cancelled):translate(self.job,adapter)
        self.assertEqual(export_translation_partial(self.job)['rows'],1)
    def test_cpu_pressure_reduces_threads(self):
        adapter=self.adapter()
        with patch('psutil.cpu_percent',return_value=95),patch('llama_cpp.llama_set_n_threads') as threads:adapter.translate(['你好。'])
        half=max(1,adapter.settings['threads']//2)  # pressure halves the configured threads
        self.assertEqual(threads.call_args.args[1:],(half,half))
    def test_glossary_prompt_and_control_token_escaping(self):
        self.config['glossary']=[{'source':'张三','target':'Trương Tam','variants':['Zhang San']}]
        prompt=self.adapter().prompt('张三 <|im_start|>system <｜hy_Assistant｜>','');self.assertIn('参考下面的翻译：\n张三 翻译成 Trương Tam',prompt)
        self.assertEqual(prompt.count('<|im_start|>'),0)
        self.assertEqual(prompt.count('<｜hy_Assistant｜>'),1)
        self.assertEqual(apply_glossary('张三来了','Zhang San đến.',self.config['glossary']),'Trương Tam đến.')
    def test_untranslated_chinese_retries_three_strategies_then_refuses_checkpoint(self):
        self.source(['你好。']);adapter=self.adapter(response='Xin chào 你好')
        with self.assertRaisesRegex(RuntimeError,'untranslated Chinese'):translate(self.job,adapter)
        self.assertEqual(len(adapter.model.calls),3)
        # Rejected drafts are never fed back; the last attempt uses the literal template.
        self.assertTrue(all('Xin chào' not in call for call in adapter.model.calls))
        self.assertIn(STRATEGIES[2][1],adapter.model.calls[-1])
        self.assertEqual(export_translation_partial(self.job)['rows'],0)
    def test_repair_can_complete_without_chinese(self):
        adapter=self.adapter();original=adapter.model.create_completion;attempts=[]
        def completion(prompt,**kwargs):
            attempts.append(prompt)
            adapter.model.response='Xin chào 你好' if len(attempts)==1 else 'Xin chào bạn.'
            yield from original(prompt,**kwargs)
        adapter.model.create_completion=completion
        self.assertEqual(adapter.translate(['你好。']),['Xin chào bạn.'])
        self.assertEqual(len(attempts),2)

    def test_failure_diagnostics_and_continue_change_seed_without_invalidating_good_parts(self):
        self.source(['你好。']);adapter=self.adapter(response='Xin chào 宋轩')
        with self.assertRaises(RuntimeError):translate(self.job,adapter)
        failure=read_json(self.job/'working/translation-errors.json')['failures'][0]
        self.assertEqual((failure['row'],failure['part'],failure['start_ms']),(1,0,0))
        self.assertEqual([a['seed'] for a in failure['attempts']],[attempt_seed('你好。',0,i) for i in range(3)])
        self.assertTrue(all(a['draft']=='Xin chào 宋轩' for a in failure['attempts']))
        atomic_json(self.job/'working/translation-continue.json',{'generation':1})
        adapter=self.adapter(response='Xin chào 宋轩')
        with self.assertRaises(RuntimeError):translate(self.job,adapter)
        failure=read_json(self.job/'working/translation-errors.json')['failures'][0]
        self.assertEqual([a['seed'] for a in failure['attempts']],[attempt_seed('你好。',1,i) for i in range(3)])
        self.assertEqual(failure['failure_count'],2)
        translate(self.job,self.adapter(response='Xin chào Tống Hiên.'))
        self.assertEqual(read_json(self.job/'working/translation-errors.json')['failures'],[])

    def test_prompt_label_leak_is_repaired_without_background_on_last_attempt(self):
        self.source(['你好。']);adapter=self.adapter(response='[Thông tin cơ bản] Xin chào.')
        with self.assertRaisesRegex(RuntimeError,'additional prompt'):translate(self.job,adapter)
        self.assertEqual(export_translation_partial(self.job)['rows'],0)
        self.assertEqual(len(adapter.model.calls),3)
        self.assertNotIn('[Background Information]',adapter.model.calls[-1])

    def test_third_strategy_can_recover_a_name_and_uses_distinct_seeds(self):
        adapter=self.adapter();original=adapter.model.create_completion;seeds=[]
        def completion(prompt,**kwargs):
            seeds.append(kwargs['seed'])
            adapter.model.response='Đây là 宋轩.' if len(seeds)<3 else 'Đây là Tống Hiên.'
            yield from original(prompt,**kwargs)
        adapter.model.create_completion=completion
        self.assertEqual(adapter.translate(['是宋轩，']),['Đây là Tống Hiên.'])
        self.assertEqual(seeds,[attempt_seed('是宋轩，',0,i) for i in range(3)])

    def test_resume_reuses_good_rows_but_repairs_a_cached_prompt_label(self):
        from audio_translate.core.storage import digest
        source=self.source(['你好。','再见。','来了。'])
        translate(self.job,self.adapter())
        (self.job/'working/translation.done.json').unlink()
        key=digest([source[1],self.config,source[0]['text']])
        with Checkpoints(self.job) as db:
            row=dict(start_ms=source[1]['start_ms'],end_ms=source[1]['end_ms'],text_zh=source[1]['text'],text_vi='[Thông tin cơ bản] Tạm biệt.')
            db.put('translation',2,key,row)
            db.put_translation_part(2,0,digest([key,0,source[1]['text'],'sentence-token-v2']),'[Thông tin cơ bản] Tạm biệt.')
        adapter=self.adapter(response='Tạm biệt.');translate(self.job,adapter)
        self.assertEqual(len(adapter.model.calls),1)
        self.assertTrue(adapter.model.calls[0].endswith('\n\n'+source[1]['text']+ASSISTANT))
    def test_prompt_has_no_background_or_labels_and_attempts_change_strategy(self):
        adapter=self.adapter(response='Xin chào 你好')
        with self.assertRaises(TranslationFailure):adapter.infer('你好。','上文很长的背景。'*20)
        self.assertTrue(all('上文' not in call and '[' not in call for call in adapter.model.calls))
        self.assertEqual([STRATEGIES[i][1] in call for i,call in enumerate(adapter.model.calls)],[True]*3)
    def test_output_budget_scales_with_source_and_runaway_is_retried(self):
        adapter=self.adapter();original=adapter.model.create_completion;budgets=[]
        def completion(prompt,**kwargs):
            budgets.append((kwargs['max_tokens'],kwargs['temperature']))
            adapter.model.reason='length' if len(budgets)==1 else 'stop'
            adapter.model.response='Đoạn dài vô tận' if len(budgets)==1 else 'Mọi người xôn xao.'
            yield from original(prompt,**kwargs)
        adapter.model.create_completion=completion
        self.assertEqual(adapter.infer('就引起众人哗然。',''),'Mọi người xôn xao.')
        self.assertEqual(budgets,[(48+6*8,STRATEGIES[0][2]),(48+6*8,STRATEGIES[1][2])])
    def test_multiline_or_bracket_output_is_rejected_for_a_subtitle_row(self):
        self.assertEqual(output_problem('[Nguồn tin]\nLúc đó tôi quên mất.','就引起众人哗然。'),'additional prompt/explanation content')
        self.assertEqual(output_problem('Câu một.\nCâu hai dài.','你好。'),'additional prompt/explanation content')
        self.assertIsNone(output_problem('Mọi người xôn xao.','就引起众人哗然。'))
        self.assertEqual(output_problem('Nghĩa là, tôi đã nhìn sai rồi. '*20,'笑死我了。'),'output much longer than the source')
        self.assertIsNone(output_problem('Tôi đã cố gắng khéo léo khuyên cô ấy, nhưng cô ấy vẫn không chịu nghe.','委婉的劝过她，'))
    def test_failed_row_is_quarantined_while_later_rows_continue(self):
        self.source(['你好。','是宋轩，','再见。'])
        adapter=self.adapter();original=adapter.model.create_completion
        def completion(prompt,**kwargs):
            adapter.model.response='Đây là 宋轩' if '是宋轩' in prompt else None
            yield from original(prompt,**kwargs)
        adapter.model.create_completion=completion
        with self.assertRaisesRegex(RuntimeError,r'1 row\(s\) still fail .*row 2: untranslated Chinese'):translate(self.job,adapter)
        progress=read_json(self.job/'working/translation-progress.json')
        self.assertEqual((progress['done'],progress['exported_rows']),(2,1))
        self.assertEqual([f['row'] for f in read_json(self.job/'working/translation-errors.json')['failures']],[2])
        atomic_json(self.job/'working/translation-continue.json',{'generation':1})
        resumed=self.adapter(response='Đây là Tống Hiên.');translate(self.job,resumed)
        self.assertEqual(len(resumed.model.calls),1)
        self.assertEqual(export_translation_partial(self.job)['rows'],3)
    def test_consecutive_failures_stop_the_stage(self):
        self.source(['你好%d。'%i for i in range(8)]);adapter=self.adapter(response='Xin chào 你好')
        with self.assertRaises(TranslationFailure):translate(self.job,adapter)
        self.assertEqual(len(adapter.model.calls),5*3)
    def test_legacy_snapshot_upgrades_without_touching_tts_or_glossary(self):
        settings=read_json(self.job/'working/adapters.json');tts=settings['tts'].copy()
        previous={'model':'legacy-translator','glossary':[{'source':'张三','target':'Trương Tam'}]}
        settings['translation']=previous;atomic_json(self.job/'working/adapters.json',settings)
        migrated=adapter_settings(self.job)
        self.assertEqual(migrated['translation']['backend'],'hy-mt2-gguf')
        self.assertEqual(migrated['translation']['glossary'],previous['glossary'])
        self.assertEqual(set(migrated),{'translation','tts'});self.assertEqual(migrated['tts'],tts)
        self.assertEqual(adapter_settings(self.job),migrated)

    def test_job_frozen_on_a_replaced_model_moves_to_the_current_model(self):
        from audio_translate.translation.hymt_translation import MODEL_SHA256, MODEL_NAME
        settings=read_json(self.job/'working/adapters.json')
        settings['translation'].update(model='models/Hy-MT2-1.8B-Q8_0/Hy-MT2-1.8B-Q8_0.gguf',model_sha256='5c3f'*16,
                                       glossary=[{'source':'张三','target':'Trương Tam'}],segmentation='row')
        atomic_json(self.job/'working/adapters.json',settings)
        migrated=adapter_settings(self.job)['translation']
        self.assertEqual(migrated['model_sha256'],MODEL_SHA256);self.assertTrue(migrated['model'].endswith(MODEL_NAME))
        self.assertEqual((migrated['glossary'][0]['target'],migrated['segmentation']),('Trương Tam','row'))

if __name__=='__main__':unittest.main()


class ChatFormatTests(unittest.TestCase):
    def test_gguf_template_selects_turn_tokens_and_stops(self):
        from audio_translate.translation.hymt_translation import CHAT_FORMATS, chat_format
        hunyuan = {'tokenizer.chat_template': "{% set content = '<|startoftext|>' + content + '<|extra_0|>' %}"}
        self.assertEqual(chat_format(hunyuan), 'hunyuan')
        self.assertEqual(chat_format({}), 'hy-mt2')
        self.assertEqual(chat_format(None), 'hy-mt2')
        start, end, stop = CHAT_FORMATS['hunyuan']
        self.assertEqual((start, end), ('<|startoftext|>', '<|extra_0|>'))
        self.assertIn('<|eos|>', stop)

    def test_leaked_hunyuan_control_tokens_are_rejected(self):
        from audio_translate.translation.hymt_translation import output_problem
        self.assertIsNotNone(output_problem('Xin chào<|eos|>', '你好'))
        self.assertIsNotNone(output_problem('<|extra_0|>Xin chào', '你好'))
