import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import manage, results
from storage import atomic_json,read_json,file_lock,LockedError
from errors import initial_steps


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.job=root/'data'/'tmp'/str(uuid.uuid4());(self.job/'working').mkdir(parents=True)
        for module,attribute,value in ((manage,'DATA',root/'data'),(results,'DATA',root/'data'),(results,'RESULTS',root/'outputs')):
            p=patch.object(module,attribute,value);p.start();self.addCleanup(p.stop)
        p=patch('license_gate.assert_allowed');p.start();self.addCleanup(p.stop)
        steps=initial_steps({});steps['DOWNLOAD']['state']='COMPLETED';steps['TRANSCRIPTION'].update(state='CANCELLED',attempt=1)
        atomic_json(self.job/'job.json',{'id':self.job.name,'workflow_no':1,'storage_scope':'workflows','status':'CANCELLED','steps':steps})
        atomic_json(self.job/'working'/'cancel.signal',{})
        atomic_json(self.job/'working'/'chunk-000000.json',[{'start_ms':0,'end_ms':1000,'text':'你好'}])

    def test_resume_preserves_checkpoint_and_queues_only_on_request(self):
        path=self.job/'working'/'chunk-000000.json';before=path.read_bytes()
        job=manage.resume(self.job.name)
        self.assertEqual(job['status'],'QUEUED');self.assertEqual(job['steps']['TRANSCRIPTION']['state'],'PENDING')
        self.assertEqual(job['steps']['DOWNLOAD']['state'],'COMPLETED');self.assertEqual(job['steps']['TRANSCRIPTION']['attempt'],1)
        self.assertEqual(path.read_bytes(),before);self.assertFalse((self.job/'working'/'cancel.signal').exists())
        with self.assertRaises(ValueError):manage.resume(self.job.name)

    def test_locked_job_cannot_resume(self):
        with file_lock(self.job/'working'/'worker.lock'),self.assertRaises(LockedError):manage.resume(self.job.name)
        self.assertEqual(read_json(self.job/'job.json')['status'],'CANCELLED')


if __name__=='__main__':unittest.main()
