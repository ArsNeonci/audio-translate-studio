import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import workflow_admission as admission
from storage import atomic_json, file_lock, LockedError
from asr_runtime import GIB


def snapshot(**changes):
    return {'available':12*GIB,'total':16*GIB,'physical_cores':8,'logical_cores':16,
            'cpu':20,'plugged':True,'hot':False,'thermal_available':False,**changes}


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        p=patch.object(admission,'DATA',self.root);p.start();self.addCleanup(p.stop)

    def assess(self,jobs=None,**hardware):
        return admission.assess(snapshot(**hardware),jobs or [],int(2.5*GIB),4)

    def test_free_hardware_allows_and_reports_sequential(self):
        result=self.assess()
        self.assertTrue(result['allowed']);self.assertEqual(result['scheduler_mode'],'sequential')
        self.assertEqual(result['estimate_basis'],'estimated')

    def test_low_ram_blocks_before_creation(self):
        result=self.assess(available=3.4*GIB)
        self.assertFalse(result['allowed']);self.assertIn('RAM',result['reasons'][0])
        with patch.object(admission,'preflight',return_value=result),patch('manage.create') as create,patch('license_gate.assert_allowed'):
            response=admission.convert('https://youtu.be/1JzKgwOESoM')
        self.assertEqual(response['status'],409);self.assertEqual(response['code'],'RESOURCE_WARNING')
        create.assert_not_called();self.assertFalse((self.root/'tmp').exists())

    def test_queue_confirmation_still_checks_but_only_creates_once(self):
        with patch.object(admission,'preflight',return_value=self.assess(available=3*GIB)) as check,patch('manage.create',return_value={'id':'new','status':'QUEUED'}) as create,patch('license_gate.assert_allowed'):
            response=admission.convert('url','voice',queue_only=True)
        check.assert_called_once();create.assert_called_once_with('url','voice')
        self.assertEqual(response['job']['status'],'QUEUED');self.assertFalse(response['assessment']['allowed'])

    def test_pending_allocations_reserved_and_loaded_model_not_double_counted(self):
        queued=[{'status':'QUEUED'}]
        self.assertFalse(self.assess(queued,available=7*GIB)['allowed'])
        loaded=[{'status':'TRANSCRIBING','_asr_loaded':True}]
        self.assertTrue(self.assess(loaded,available=7*GIB)['allowed'])

    def test_cpu_budget_heat_and_battery(self):
        self.assertFalse(self.assess([{'status':'QUEUED'}]*2)['allowed'])
        self.assertFalse(self.assess(cpu=82)['allowed'])
        self.assertFalse(self.assess(hot=True)['allowed'])
        self.assertFalse(self.assess(cpu=62,plugged=False)['allowed'])

    def test_terminal_ignored_legacy_deduplicated_tools_counted(self):
        for root,identity,state in [('tmp','same','QUEUED'),('jobs','same','QUEUED'),('tool-tmp','tool','VAD'),('tmp','cancelled','CANCELLED'),('tmp','complete','COMPLETED')]:
            atomic_json(self.root/root/identity/'job.json',{'id':identity,'status':state})
        self.assertEqual(len(admission.pending_jobs()),2)

    def test_no_profile_uses_estimate_no_fingerprint_or_model(self):
        with patch.object(admission,'fingerprint') as identify:
            self.assertEqual(admission.model_budget(8),(int(2.5*GIB),4,'estimated'))
        identify.assert_not_called()

    def test_valid_profile_and_stale_profile(self):
        import time
        profile={'fingerprint':'cpu','created_at':time.time(),'peak_bytes':GIB,'single_threads':6}
        atomic_json(self.root/'config'/'asr-autotune.json',profile)
        with patch.object(admission,'fingerprint',return_value='cpu'):
            self.assertEqual(admission.model_budget(8),(int(1.25*GIB),6,'measured'))
            profile.update(workers=2,threads=3);atomic_json(self.root/'config'/'asr-autotune.json',profile)
            self.assertEqual(admission.model_budget(8),(int(2.5*GIB),6,'measured'))
            profile['created_at']=0;atomic_json(self.root/'config'/'asr-autotune.json',profile)
            self.assertEqual(admission.model_budget(8)[2],'estimated')

    def test_busy_convert_lock_prevents_second_create(self):
        with file_lock(self.root/'management-locks'/'convert-admission.lock'),patch('manage.create') as create,patch('license_gate.assert_allowed'):
            with self.assertRaises(LockedError):admission.convert('url')
        create.assert_not_called()


if __name__=='__main__':unittest.main()
