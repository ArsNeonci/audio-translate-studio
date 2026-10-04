import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from audio_translate.workflow import manage
from audio_translate.workflow import results
from audio_translate.core.control import check_cancel, Cancelled, complete_task, cancel_run
from audio_translate.core.errors import initial_steps, record_failure
from audio_translate.core.storage import atomic_json, read_json, file_lock, Checkpoints
from audio_translate.workflow.retry import request_retry


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)/'data';self.job=self.data/'tmp'/str(uuid.uuid4())
        (self.job/'working').mkdir(parents=True);(self.job/'source').mkdir()
        for module,attribute,value in ((manage,'DATA',self.data),(results,'DATA',self.data),(results,'RESULTS',self.data/'results')):
            p=patch.object(module,attribute,value);p.start();self.addCleanup(p.stop)
        p=patch('audio_translate.core.license_gate.assert_allowed');p.start();self.addCleanup(p.stop)
        steps=initial_steps({});steps['DOWNLOAD']['state']='COMPLETED';steps['TRANSCRIPTION'].update(state='RUNNING',attempt=1)
        atomic_json(self.job/'job.json',{'id':self.job.name,'workflow_no':1,'storage_scope':'workflows','status':'TRANSCRIBING','steps':steps,'created_at':'2026-10-03','url':'fixture','name':'fixture'})
        (self.job/'source'/'audio.wav').write_bytes(b'previous source')
        atomic_json(self.job/'working'/'chunk-000000.json',[{'start_ms':0,'end_ms':1,'text':'cached'}])
        results.metadata(self.job)

    def test_pause_when_idle_saves_and_resume_keeps_checkpoint(self):
        before=(self.job/'working'/'chunk-000000.json').read_bytes()
        manage.cancel(self.job.name,mode='pause')
        self.assertEqual(read_json(self.job/'job.json')['status'],'PAUSED')
        self.assertEqual(manage.resume(self.job.name)['status'],'QUEUED')
        self.assertEqual((self.job/'working'/'chunk-000000.json').read_bytes(),before)

    def test_running_pause_does_not_mutate_job_until_worker_ack(self):
        before=(self.job/'job.json').read_bytes()
        with file_lock(self.job/'working'/'worker.lock'):manage.cancel(self.job.name,mode='pause')
        self.assertEqual((self.job/'job.json').read_bytes(),before)
        self.assertEqual(read_json(self.job/'working'/'cancel.signal')['mode'],'pause')
        cancel_run(self.job,'TRANSCRIPTION')
        self.assertEqual(read_json(self.job/'job.json')['steps']['TRANSCRIPTION']['state'],'PAUSED')

    def test_pause_finishes_current_adapter_task_then_stops_next(self):
        @complete_task
        def task():
            atomic_json(self.job/'working'/'cancel.signal',{'mode':'pause'})
            check_cancel(self.job)
            atomic_json(self.job/'working'/'chunk-000001.json',[])
        task()
        self.assertTrue((self.job/'working'/'chunk-000001.json').exists())
        with self.assertRaises(Cancelled):check_cancel(self.job)

    def test_abort_can_interrupt_adapter_instead_of_ignoring_signal(self):
        atomic_json(self.job/'working'/'cancel.signal',{'mode':'abort'})
        @complete_task
        def task():check_cancel(self.job)
        with self.assertRaises(Cancelled):task()

    def test_wrong_confirmation_deletes_nothing(self):
        with self.assertRaises(ValueError):manage.abort(self.job.name,2)
        self.assertTrue((self.job/'source'/'audio.wav').exists())
        self.assertFalse((self.job/'working'/'delete-request.json').exists())

    def test_abort_waits_for_worker_then_removes_only_this_run(self):
        shared=self.data/'model-cache'/'keep.bin';shared.parent.mkdir();shared.write_bytes(b'model')
        other=self.data/'tmp'/str(uuid.uuid4())/'job.json';atomic_json(other,{'keep':True})
        published=results.destination(self.job.name)
        with file_lock(self.job/'working'/'worker.lock'):
            response=manage.abort(self.job.name,1)
            self.assertTrue(response['deletion_pending']);self.assertTrue(self.job.exists())
            with self.assertRaises(Exception):manage.resume(self.job.name)
        cancel_run(self.job,'TRANSCRIPTION');manage.finish_abort(self.job.name)
        self.assertFalse(self.job.exists());self.assertFalse(published.exists())
        self.assertEqual(shared.read_bytes(),b'model');self.assertTrue(other.exists())

    def test_abort_queued_job_deletes_immediately(self):
        job=read_json(self.job/'job.json');job['status']='QUEUED';job['steps']['TRANSCRIPTION']['state']='PENDING';atomic_json(self.job/'job.json',job)
        self.assertTrue(manage.abort(self.job.name,1)['deleted']);self.assertFalse(self.job.exists())

    def test_resume_error_fresh_restart_only_failed_stage(self):
        manage.cancel(self.job.name,mode='pause');manage.resume(self.job.name)
        record_failure(self.job,'TRANSCRIPTION',RuntimeError('resume failed'))
        source=(self.job/'source'/'audio.wav').read_bytes()
        request_retry(self.job,'TRANSCRIPTION',fresh=True)
        job=read_json(self.job/'job.json')
        self.assertEqual(job['retry_step'],'TRANSCRIPTION');self.assertEqual(job['steps']['DOWNLOAD']['state'],'COMPLETED')
        self.assertEqual((self.job/'source'/'audio.wav').read_bytes(),source)
        self.assertFalse((self.job/'working'/'chunk-000000.json').exists())
        self.assertEqual(job['chunks_done'],0)

    def test_restart_translation_removes_only_its_sqlite_rows_and_output(self):
        job=read_json(self.job/'job.json');job['steps']['TRANSCRIPTION']['state']='COMPLETED';job['steps']['TRANSLATION']['state']='FAILED';job['status']='FAILED';atomic_json(self.job/'job.json',job)
        (self.job/'transcript.zh.jsonl').write_text('previous',encoding='utf8')
        (self.job/'transcript.vi.jsonl').write_text('broken',encoding='utf8')
        with Checkpoints(self.job) as db:
            db.put('translation',1,'fingerprint',{'text_vi':'old'})
            db.put_translation_part(1,0,'part-fingerprint','old part')
            db.put('moderation',1,'fingerprint',{'keep':True})
        request_retry(self.job,'TRANSLATION',fresh=True)
        self.assertFalse((self.job/'transcript.vi.jsonl').exists());self.assertEqual((self.job/'transcript.zh.jsonl').read_text(),'previous')
        with Checkpoints(self.job) as db:
            self.assertIsNone(db.get('translation',1,'fingerprint'));self.assertEqual(db.get('moderation',1,'fingerprint'),{'keep':True})
            self.assertIsNone(db.get_translation_part(1,0,'part-fingerprint'))

    def test_continue_failed_translation_preserves_database_and_can_be_repeated(self):
        job=read_json(self.job/'job.json');job['steps']['TRANSCRIPTION']['state']='COMPLETED'
        job['steps']['TRANSLATION'].update(state='FAILED',duration_ms=1234,progress=50)
        job.update(status='FAILED',failed_stage='translation');atomic_json(self.job/'job.json',job)
        (self.job/'transcript.zh.jsonl').write_text('{"start_ms":0,"end_ms":1,"text":"你好"}\n',encoding='utf8')
        with Checkpoints(self.job) as db:
            db.put('translation',2,'good',{'text_vi':'saved after gap'})
            db.put_translation_part(1,0,'good-part','saved part')
        database=self.job/'working/postprocess.sqlite3';before=database.read_bytes()
        result=manage.resume(self.job.name)
        self.assertEqual(result['status'],'QUEUED')
        self.assertEqual(result['steps']['TRANSLATION']['resume_duration_ms'],1234)
        self.assertEqual(result['steps']['TRANSCRIPTION']['state'],'COMPLETED')
        self.assertEqual(database.read_bytes(),before)
        with self.assertRaises(ValueError):manage.resume(self.job.name)
        record_failure(self.job,'TRANSLATION',RuntimeError('still failed'))
        manage.resume(self.job.name)
        self.assertEqual(read_json(self.job/'working/translation-continue.json')['generation'],2)
        self.assertEqual(database.read_bytes(),before)

    def test_continue_rejects_failed_other_stage_and_unfinished_predecessors(self):
        record_failure(self.job,'TRANSCRIPTION',RuntimeError('failed'))
        with self.assertRaises(ValueError):manage.resume(self.job.name)
        job=read_json(self.job/'job.json');job['steps']['TRANSLATION']['state']='FAILED';atomic_json(self.job/'job.json',job)
        with self.assertRaises(ValueError):manage.resume(self.job.name)


if __name__=='__main__':unittest.main()
