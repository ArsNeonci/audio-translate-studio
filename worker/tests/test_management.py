"""Acceptance coverage for numbering, lifecycle, migration and standalone nodes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid
from audio_translate.workflow import manage
from audio_translate.workflow import results
from audio_translate.tts import voices
from audio_translate.core.control import Cancelled, check_cancel, cancel_run, elapsed, end_run
from audio_translate.core.errors import STEPS, initial_steps, transition
from audio_translate.core.storage import atomic_json, read_json, update_job, file_digest, progress, file_lock, LockedError
from audio_translate.tts.adapters import adapter_settings
from audio_translate.workflow.orchestrator import run
from audio_translate.workflow.postprocess import translate,moderate,synthesize
from audio_translate.moderation.rules import ReplacementRules
from audio_translate.workflow.retry import request_retry
from tests.test_postprocess import FakeTranslator,FakeTTS

class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)/'data';self.output=self.data/'results'
        for module,attr,value in [(manage,'DATA',self.data),(results,'DATA',self.data),(results,'RESULTS',self.output),(voices,'DATA',self.data)]:
            p=patch.object(module,attr,value);p.start();self.addCleanup(p.stop)
        p=patch('audio_translate.core.license_gate.assert_allowed',return_value=True);p.start();self.addCleanup(p.stop)
        self.catalog=voices.discover();self.voice=self.catalog['voices'][0]['id']
        self.rules=ReplacementRules(self.data/'config')
    def job(self):
        j=manage.create('https://youtu.be/1JzKgwOESoM',self.voice);return results.workspace(j['id'])
    def prepare(self,d):
        j=read_json(d/'job.json');steps=j['steps']
        for s in STEPS[:2]:steps[s]['state']='COMPLETED'
        update_job(d,steps=steps)
        (d/'transcript.zh.md').write_text('你好',encoding='utf-8')
        (d/'transcript.zh.jsonl').write_text(json.dumps({'start_ms':0,'end_ms':1000,'text':'你好'},ensure_ascii=False)+'\n',encoding='utf-8')
    def child(self,d,seen=None):
        def execute(command,**kwargs):
            stage=command[-1]
            if seen is not None:seen.append(stage)
            if stage=='translation':translate(d,FakeTranslator())
            elif stage=='moderation':moderate(d,self.rules)
            elif stage=='tts':synthesize(d,FakeTTS())
            else:raise AssertionError('Unexpected predecessor run')
            return Mock(returncode=0)
        return execute
    def complete(self,d):
        self.prepare(d)
        with patch('audio_translate.workflow.orchestrator.subprocess.run',side_effect=self.child(d)):self.assertEqual(run(d),0)
        return results.destination(d.name)
    def upload(self,text='你好\n',tool='translation',name='input.txt',mime='text/plain',voice=None):
        p=self.data/'uploads'/f'{uuid.uuid4()}.upload';p.parent.mkdir(exist_ok=True,parents=True);p.write_text(text,encoding='utf-8')
        j=manage.create(tool=tool,upload=p,input_name=name,mime=mime,voice=voice);return results.workspace(j['id'])
    def test_01_first_workflow_prefixes_all_outputs(self):
        d=self.job();out=self.complete(d)
        self.assertEqual(read_json(d/'job.json')['workflow_no'],1)
        for f in read_json(out/'outputs.json')['files']:self.assertTrue(Path(f['path']).name.startswith('000001-'))
    def test_02_second_number_and_no_reuse_after_delete(self):
        a=self.job();b=self.job();self.assertEqual(read_json(b/'job.json')['workflow_no'],2)
        update_job(a,status='FAILED');manage.hard_delete(a.name,1)
        c=self.job();self.assertEqual(read_json(c/'job.json')['workflow_no'],3)
    def test_03_retry_preserves_number(self):
        d=self.job();j=read_json(d/'job.json');j['steps']['DOWNLOAD']['state']='FAILED';j['status']='FAILED';atomic_json(d/'job.json',j)
        request_retry(d,'DOWNLOAD');self.assertEqual(read_json(d/'job.json')['workflow_no'],1)
    def test_04_reprocess_number_and_predecessors(self):
        d=self.job();out=self.complete(d);sha=file_digest(out/'transcription'/'000001-transcript.zh.md')
        manage.reprocess(d.name,'TRANSLATION');seen=[]
        self.assertTrue(all(f['status']=='STALE' for f in read_json(out/'outputs.json')['files'] if f['step'] in STEPS[2:]))
        with patch('audio_translate.workflow.orchestrator.subprocess.run',side_effect=self.child(d,seen)):self.assertEqual(run(d),0)
        self.assertEqual(seen,['translation','moderation','tts']);self.assertEqual(file_digest(out/'transcription'/'000001-transcript.zh.md'),sha)
        self.assertEqual(read_json(d/'job.json')['workflow_no'],1)
    def test_05_progress_clamped_and_unknown_indeterminate(self):
        d=self.job();progress(d,'download','DOWNLOADING',200,100);self.assertEqual(read_json(d/'job.json')['steps']['DOWNLOAD']['progress'],100)
        progress(d,'download','DOWNLOADING',1,None);self.assertIsNone(read_json(d/'job.json')['progress'])
    def test_06_progress_numeric_two_decimal_precision(self):
        d=self.job();progress(d,'download','DOWNLOADING',1,3);self.assertEqual(read_json(d/'job.json')['steps']['DOWNLOAD']['progress'],33.33)
    def test_07_stage_timing_and_attempt_reset(self):
        d=self.job();transition(d,'DOWNLOAD','RUNNING');j=read_json(d/'job.json');j['steps']['DOWNLOAD']['started_at']='2026-01-01T00:00:00+00:00';atomic_json(d/'job.json',j)
        with patch('audio_translate.core.control.now',return_value='2026-01-01T00:00:02.345000+00:00'):transition(d,'DOWNLOAD','COMPLETED')
        self.assertEqual(read_json(d/'job.json')['steps']['DOWNLOAD']['duration_ms'],2345)
        transition(d,'DOWNLOAD','RUNNING');s=read_json(d/'job.json')['steps']['DOWNLOAD'];self.assertEqual(s['duration_ms'],0);self.assertIsNone(s['completed_at']);self.assertEqual(s['attempt'],2)
    def test_08_workflow_total_persisted(self):
        d=self.job();self.complete(d);j=read_json(d/'job.json');self.assertIsNotNone(j['started_at']);self.assertIsNotNone(j['completed_at']);self.assertGreater(j['total_duration_ms'],0)
    def test_09_all_source_voices_discovered(self):
        source=voices.vieneu_source()/'src'/'vieneu'/'assets'/'voices_v3_turbo.json'
        names=set(read_json(source)['presets']);self.assertTrue(names.issubset({v['id'] for v in self.catalog['voices']}))
    def test_10_preference_survives_read_and_missing_voice_fallback(self):
        chosen=self.catalog['voices'][-1]['id'];voices.select(chosen);self.assertEqual(voices.discover()['selected_voice_id'],chosen)
        atomic_json(self.data/'config'/'preferences.json',{'last_vietnamese_voice_id':'removed'});self.assertEqual(voices.discover()['selected_voice_id'],self.catalog['default_voice_id'])
    def test_11_standalone_translation_executes_only_translation(self):
        d=self.upload();seen=[]
        with patch('audio_translate.workflow.orchestrator.subprocess.run',side_effect=self.child(d,seen)):self.assertEqual(run(d),0)
        self.assertEqual(seen,['translation']);self.assertEqual(read_json(d/'job.json')['status'],'COMPLETED');self.assertTrue((results.destination(d.name)/'translation'/'000001-transcript.vi.md').is_file())
    def test_12_standalone_tts_passes_selected_voice(self):
        chosen=self.catalog['voices'][-1]['id'];d=self.upload('Xin chào\n','tts',voice=chosen);self.assertEqual(adapter_settings(d)['tts']['voice'],chosen)
        with patch('audio_translate.workflow.orchestrator.subprocess.run',side_effect=self.child(d)):self.assertEqual(run(d),0)
        self.assertTrue((results.destination(d.name)/'tts'/'000001-voice.vi.wav').is_file())
    def test_13_tool_history_storage_separate(self):
        a=self.job();b=self.upload();self.assertEqual(len(manage.history('workflows')),1);self.assertEqual(len(manage.history('tools')),1)
        self.assertNotEqual(results.destination(a.name),results.destination(b.name));self.assertEqual(read_json(b/'job.json')['workflow_no'],1)
    def test_14_hard_delete_removes_all_and_legacy_backup(self):
        d=self.job();out=self.complete(d);legacy=self.output/d.name;legacy.mkdir();(legacy/'old.txt').write_text('backup')
        (d/'working'/'x.tmp').write_text('partial');manage.hard_delete(d.name,1)
        self.assertFalse(d.exists());self.assertFalse(out.exists());self.assertFalse(legacy.exists());self.assertEqual(manage.history('workflows'),[])
        with manage.registry() as db:self.assertIsNone(db.execute('SELECT id FROM runs WHERE id=?',(d.name,)).fetchone())
    def test_15_delete_does_not_touch_other_workflow_or_models(self):
        a=self.job();b=self.job();out=self.complete(b);update_job(a,status='FAILED');sha=file_digest(out/'tts'/'000002-voice.vi.wav');manage.hard_delete(a.name,1)
        self.assertEqual(file_digest(out/'tts'/'000002-voice.vi.wav'),sha);self.assertTrue(b.exists())
    def test_16_reprocess_tts_only(self):
        d=self.job();self.complete(d);manage.reprocess(d.name,'TTS');seen=[]
        with patch('audio_translate.workflow.orchestrator.subprocess.run',side_effect=self.child(d,seen)):self.assertEqual(run(d),0)
        self.assertEqual(seen,['tts'])
    def test_17_atomic_publish_replaces_old_complete_artifact(self):
        d=self.job();self.prepare(d);results.publish_step(d,'TRANSCRIPTION');out=results.destination(d.name)
        (d/'transcript.zh.md').write_text('new',encoding='utf-8');results.publish_step(d,'TRANSCRIPTION');self.assertEqual((out/'transcription'/'000001-transcript.zh.md').read_text(),'new');self.assertEqual(list(out.rglob('*.tmp')),[])
    def test_18_failed_publish_preserves_old_artifact(self):
        d=self.job();out=self.complete(d);target=out/'translation'/'000001-transcript.vi.md';sha=file_digest(target)
        (d/'transcript.vi.md').write_text('replacement')
        with patch('audio_translate.workflow.results.shutil.copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):results.publish_step(d,'TRANSLATION')
        self.assertEqual(file_digest(target),sha)
    def test_19_cancel_cleans_incomplete_without_upstream_delete(self):
        d=self.job();self.prepare(d);results.publish_step(d,'TRANSCRIPTION');sha=file_digest(d/'transcript.zh.jsonl')
        transition(d,'TRANSLATION','RUNNING');(d/'transcript.vi.md.tmp').write_text('partial');cancel_run(d,'TRANSLATION')
        self.assertFalse((d/'transcript.vi.md.tmp').exists());self.assertEqual(file_digest(d/'transcript.zh.jsonl'),sha);self.assertEqual(read_json(d/'job.json')['steps']['TRANSCRIPTION']['state'],'COMPLETED')
    def test_20_cancel_signal_while_locked_and_resume(self):
        d=self.job();self.prepare(d)
        with file_lock(d/'working'/'worker.lock'):manage.cancel(d.name)
        with self.assertRaises(Cancelled):check_cancel(d)
        cancel_run(d,'TRANSLATION');manage.reprocess(d.name,'TRANSLATION');self.assertFalse((d/'working'/'cancel.signal').exists())
    def test_21_cancelled_workflow_runs_downstream_later(self):
        d=self.job();self.prepare(d);cancel_run(d,'TRANSLATION');manage.reprocess(d.name,'TRANSLATION')
        with patch('audio_translate.workflow.orchestrator.subprocess.run',side_effect=self.child(d)):self.assertEqual(run(d),0)
        self.assertEqual(read_json(d/'job.json')['status'],'COMPLETED')
    def test_22_restart_retains_number_history_timing(self):
        d=self.job();out=self.complete(d);old=read_json(out/'job.json');manage.migrate();new=manage.history('workflows')[0]
        self.assertEqual(new['workflow_no'],old['workflow_no']);self.assertEqual(new['total_duration_ms'],old['total_duration_ms']);self.assertEqual(len(new['files']),9)
    def test_23_expired_license_blocks_tools_and_reprocess(self):
        d=self.job();self.complete(d)
        from audio_translate.core.license_gate import LicenseError
        with patch('audio_translate.core.license_gate.assert_allowed',side_effect=LicenseError('EXPIRED')):
            with self.assertRaises(LicenseError):self.upload()
            with self.assertRaises(LicenseError):manage.reprocess(d.name,'TTS')
            manage.hard_delete(d.name,1)
    def test_24_invalid_upload_extensions_content_and_paths(self):
        for text,name,mime in [('bad','bad.exe','text/plain'),('\x00bin','bad.txt','text/plain'),('x'*65537,'big.txt','text/plain'),('{"text":"x"}','bad.jsonl','application/json')]:
            with self.assertRaises(ValueError):self.upload(text,name=name,mime=mime)
        with self.assertRaises(ValueError):manage.safe_directory(self.data.parent,self.data)
        with self.assertRaises(ValueError):results.workspace('../../other')
    def test_25_migration_backups_order_collision_and_legacy_files(self):
        older,newer=str(uuid.uuid4()),str(uuid.uuid4())
        for job_id,date in [(newer,'2026-02-01'),(older,'2026-01-01')]:
            d=self.data/'jobs'/job_id;atomic_json(d/'job.json',{'id':job_id,'created_at':date,'status':'FAILED','name':date})
            (d/'transcript.zh.jsonl').write_text('{"start_ms":0,"end_ms":1,"text":"你好"}\n',encoding='utf-8');(d/'transcript.zh.md').write_text('你好',encoding='utf-8');results.publish_step(d,'TRANSCRIPTION')
        manage.migrate();a=results.workspace(older);b=results.workspace(newer)
        self.assertEqual(read_json(a/'job.json')['workflow_no'],1);self.assertEqual(read_json(b/'job.json')['workflow_no'],2)
        self.assertTrue((a/'working'/'migration-v3-original.json').is_file());self.assertTrue((self.output/older/'transcription'/'transcript.zh.md').is_file())
        with manage.registry() as db:
            with self.assertRaises(sqlite3.IntegrityError):manage.allocate(db,str(uuid.uuid4()),'workflows',1)
    def test_26_reprocess_rejects_incomplete_predecessors_and_busy(self):
        d=self.job();update_job(d,status='FAILED')
        with self.assertRaises(ValueError):manage.reprocess(d.name,'TRANSLATION')
        update_job(d,status='QUEUED')
        with self.assertRaises(ValueError):manage.reprocess(d.name,'DOWNLOAD')
    def test_27_delete_requires_exact_confirmation_and_lock(self):
        d=self.job();update_job(d,status='FAILED')
        with self.assertRaises(ValueError):manage.hard_delete(d.name,2)
        with file_lock(d/'working'/'worker.lock'):
            with self.assertRaises(LockedError):manage.hard_delete(d.name,1)
        self.assertTrue(d.exists())
    def test_28_standalone_moderation_reuses_rules(self):
        self.rules.mutate('add',{'source':'Xin chào','replacement':'Chào bạn'})
        d=self.upload('Xin chào\n','moderation')
        with patch('audio_translate.workflow.orchestrator.subprocess.run',side_effect=self.child(d)):self.assertEqual(run(d),0)
        self.assertIn('Chào bạn',(d/'transcript.vi.moderated.md').read_text(encoding='utf-8'))
    def test_29_concurrent_sequence_allocation_is_unique(self):
        from concurrent.futures import ThreadPoolExecutor
        def allocate(_):
            with manage.registry() as db:return manage.allocate(db,str(uuid.uuid4()),'workflows')
        with ThreadPoolExecutor(max_workers=4) as pool:numbers=list(pool.map(allocate,range(12)))
        self.assertEqual(sorted(numbers),list(range(1,13)))
    def test_30_archive_only_migration_restores_reprocess_inputs(self):
        d=self.job();out=self.complete(d);legacy=self.output/d.name
        import shutil
        legacy.mkdir()
        job=read_json(d/'job.json');job.pop('workflow_no');job.pop('storage_scope');atomic_json(legacy/'job.json',job)
        files=[]
        original={kind:relative for items in results.FILES.values() for kind,_,relative in items}
        for item in read_json(out/'outputs.json')['files']:
            target=legacy/original[item['type']];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out/item['path'],target);files.append({**item,'path':original[item['type']]})
        atomic_json(legacy/'outputs.json',{'job_id':d.name,'files':files});shutil.rmtree(d);shutil.rmtree(out)
        manage.migrate();restored=results.workspace(d.name)
        self.assertTrue((restored/'transcript.vi.moderated.jsonl').is_file());self.assertTrue(legacy.exists());manage.reprocess(d.name,'TTS')
    def test_31_delete_rejects_cross_history_scope(self):
        d=self.upload();update_job(d,status='FAILED')
        with self.assertRaises(ValueError):manage.hard_delete(d.name,1,'workflows')
        self.assertTrue(d.exists())
    def test_32_audio_input_validation_and_same_adapter_source(self):
        import wave
        p=self.data/'uploads'/'audio.upload';p.parent.mkdir(parents=True)
        with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*16000)
        j=manage.create(tool='transcription',upload=p,input_name='audio.wav',mime='audio/wav');d=results.workspace(j['id'])
        self.assertEqual(j['duration_ms'],500);self.assertTrue((d/'source'/'audio.wav').is_file())
        with self.assertRaises(ValueError):manage.create(tool='transcription',upload=p,input_name='audio.mp3',mime='audio/mpeg')
    def test_34b_the_source_audio_appears_in_history_and_resolves_for_the_download_and_player(self):
        """Regression: the audio was published but history() filtered it out (the public summary lacked source_ext), so the player got 404."""
        import wave
        p=self.data/'uploads'/'a.upload';p.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(16000))
        j=manage.create(voice=self.voice,upload=p,input_name='clip.wav',mime='audio/wav');d=results.workspace(j['id'])
        steps=read_json(d/'job.json')['steps'];steps['DOWNLOAD']['state']='COMPLETED';update_job(d,steps=steps)
        results.import_existing(d)                                   # publishes the Download stage
        public=read_json(results.destination(j['id'])/'job.json')    # the summary every reader sees
        self.assertEqual(public['source_ext'],'.wav');self.assertIsNone(public['tool_steps'])
        listed=next(h for h in manage.history('workflows') if h['id']==j['id'])
        self.assertEqual([(f['type'],f['step']) for f in listed['files']],[('SOURCE_AUDIO','DOWNLOAD')])
        self.assertEqual(listed['steps']['DOWNLOAD']['output_manifest'][0]['type'],'SOURCE_AUDIO')
        item=next(f for f in listed['files'] if f['id']=='SOURCE_AUDIO')
        resolved=results.destination(j['id'])/item['path']
        self.assertTrue(resolved.is_file());self.assertEqual(resolved.read_bytes(),(d/'source'/'audio.wav').read_bytes())
    def test_33_history_reads_live_progress_without_exposing_inputs(self):
        d=self.upload();transition(d,'TRANSLATION','RUNNING');progress(d,'translation','TRANSLATING',1,3)
        history=manage.history('tools')[0]
        self.assertEqual(history['progress'],33.33);self.assertEqual(history['steps']['TRANSLATION']['progress'],33.33)
        self.assertNotIn('upload_file',history);self.assertEqual(history['files'],[])

    def test_34_workflow_from_audio_file_skips_youtube_and_keeps_source(self):
        import wave
        from audio_translate.transcription import pipeline
        from audio_translate.workflow.stage_reset import reset
        p=self.data/'uploads'/'audio.upload';p.parent.mkdir(parents=True)
        with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*16000)
        j=manage.create(voice=self.voice,upload=p,input_name='clip.wav',mime='audio/wav');d=results.workspace(j['id'])
        self.assertEqual((j['storage_scope'],j['name'],j['url'],j['duration_ms']),('workflows','clip.wav','',500))
        self.assertTrue(j['source_upload']);self.assertNotIn('tool_type',j);self.assertNotIn('tool_steps',j)
        source=d/'source'/'audio.wav';self.assertTrue(source.is_file())
        with patch('yt_dlp.YoutubeDL',side_effect=AssertionError('YouTube must not be called')):
            self.assertEqual(pipeline.download(d),source)
        reset(d,'DOWNLOAD');self.assertTrue(source.is_file())  # a fresh Download restart keeps the only copy
        update_job(d,status='FAILED');manage.reprocess(d.name,'DOWNLOAD');self.assertTrue(source.is_file())
        self.assertEqual([h['id'] for h in manage.history('workflows')],[j['id']]);self.assertEqual(manage.history('tools'),[])
        source.unlink()
        with self.assertRaisesRegex(ValueError,'tạo workflow mới'):pipeline.download(d)
        with self.assertRaises(ValueError):manage.create('https://youtu.be/1JzKgwOESoM',self.voice,upload=p,input_name='clip.wav',mime='audio/wav')
        with self.assertRaises(ValueError):manage.create(voice=self.voice,upload=p,input_name='clip.mp3',mime='audio/mpeg')
import sqlite3
if __name__=='__main__':unittest.main()
