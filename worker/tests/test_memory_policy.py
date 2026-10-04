import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audio_translate.transcription import asr_runtime as runtime
from audio_translate.core import memory_policy as policy
from audio_translate.transcription import transcription_progress as telemetry
from audio_translate.workflow import workflow_admission as admission
from audio_translate.core.storage import atomic_json,read_json
from audio_translate.core.control import Cancelled


class MemoryPolicyTests(unittest.TestCase):
    def snapshot(self, **changes):
        return {'total':16*policy.GIB,'available':int(4.5*policy.GIB),
                'commit_available':10*policy.GIB,'physical_cores':8,'cpu':10,
                'plugged':True,'hot':False,'thermal_available':False,**changes}

    def test_single_worker_can_start_at_45_gib_without_pool(self):
        self.assertTrue(policy.fits(self.snapshot(),2*policy.GIB))
        self.assertFalse(runtime.may_add(self.snapshot(),2*policy.GIB))
        result=admission.assess(self.snapshot(),[],int(2.5*policy.GIB),4)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['required_available_gib'],4.5)
        self.assertFalse(admission.assess(self.snapshot(),[{'status':'QUEUED'}],int(2.5*policy.GIB),4)['allowed'])

    def test_commit_exhaustion_blocks_even_with_physical_ram(self):
        snapshot=self.snapshot(available=8*policy.GIB,commit_available=policy.GIB)
        self.assertFalse(policy.fits(snapshot,2*policy.GIB))
        self.assertFalse(admission.assess(snapshot,[],int(2.5*policy.GIB),4)['allowed'])

    def test_reserves_and_measured_peak(self):
        for total in (8,16,32):
            self.assertEqual(policy.required(total*policy.GIB,2*policy.GIB),int(4.5*policy.GIB))
        self.assertEqual(policy.required(64*policy.GIB,6*policy.GIB),int(4.5*policy.GIB))
        self.assertEqual(policy.required(16*policy.GIB,policy.GIB,parallel=True),int(7.5*policy.GIB))

    def test_worker_thresholds_and_loaded_memory_not_counted_twice(self):
        for gib,count in ((4.49,0),(4.5,1),(7.49,1),(7.5,2),(10.5,3),(13.5,4),(49.5,16),(97.5,32)):
            self.assertEqual(policy.worker_limit(int(gib*policy.GIB)),count)
        self.assertEqual(policy.worker_limit(int(4.5*policy.GIB),loaded_workers=1),2)
        self.assertTrue(runtime.may_add(self.snapshot(),2*policy.GIB,loaded_workers=1))
        self.assertFalse(runtime.may_add(self.snapshot(available=int(4.49*policy.GIB)),2*policy.GIB,loaded_workers=1))

    def test_config_changes_are_read_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'asr-memory.json'
            values=policy.settings()
            with patch.object(policy,'CONFIG',config):
                atomic_json(config,{**values,'start_free_gib':5})
                self.assertEqual(policy.worker_limit(int(4.5*policy.GIB)),0)
                atomic_json(config,values)
                self.assertEqual(policy.worker_limit(int(4.5*policy.GIB)),1)

    def test_more_ram_does_not_override_cpu_battery_or_thermal_limits(self):
        ample=self.snapshot(available=64*policy.GIB,commit_available=64*policy.GIB)
        self.assertTrue(runtime.may_add(ample,2*policy.GIB,loaded_workers=1))
        for changes in ({'cpu':80},{'cpu':90},{'plugged':False,'cpu':60},{'hot':True}):
            self.assertFalse(runtime.may_add({**ample,**changes},2*policy.GIB,loaded_workers=1))
        with patch.dict('os.environ',{'ASR_CPU_TARGET':'70'}):
            self.assertFalse(runtime.may_add({**ample,'cpu':65},2*policy.GIB,loaded_workers=1))

    def test_parallel_reserve_15_gib_keeps_model_allocation_and_commit_check(self):
        for total in (8,16,32,64):
            self.assertEqual(policy.reserve(total*policy.GIB,parallel=True),int(1.5*policy.GIB))
        self.assertTrue(runtime.may_add(self.snapshot(available=int(7.5*policy.GIB)),2*policy.GIB))
        self.assertFalse(runtime.may_add(self.snapshot(available=int(7.49*policy.GIB)),2*policy.GIB))
        self.assertFalse(runtime.may_add(self.snapshot(available=8*policy.GIB,commit_available=policy.GIB),2*policy.GIB))

    def test_low_memory_defers_benchmark_not_recognition(self):
        with (patch.object(runtime,'fingerprint',return_value='fake'),patch.object(runtime,'file_lock'),patch.object(runtime,'PROFILE',Path('nonexistent-profile')),
            patch.object(runtime,'hardware',return_value=self.snapshot()),patch.object(runtime,'wait_memory'),patch.object(runtime,'measure') as measure):
            profile=runtime.tune(Path('.'),None,[{}])
        self.assertEqual(profile['workers'],1)
        self.assertTrue(profile['tuning_deferred'])
        measure.assert_not_called()

    def test_timeout_pauses_with_checkpoints_and_excludes_wait_from_elapsed(self):
        with tempfile.TemporaryDirectory() as directory:
            job=Path(directory);(job/'working').mkdir()
            atomic_json(job/'job.json',{})
            atomic_json(job/'working'/'chunk-000000.json',[])
            with self.assertRaises(Cancelled):
                with telemetry.phase(job,3),patch.object(runtime,'hardware',return_value=self.snapshot(available=policy.GIB)),patch.object(runtime.time,'sleep'),patch.object(runtime.time,'monotonic',side_effect=[0,0,121,122]):
                    runtime.wait_memory(job,2*policy.GIB,'CALIBRATION')
            self.assertEqual(read_json(job/'working'/'cancel.signal')['mode'],'pause')
            self.assertTrue((job/'working'/'chunk-000000.json').exists())
            step=telemetry.load(job)['steps'][2]
            self.assertEqual(step['memory_wait_ms'],122000)
            self.assertEqual(step['duration_ms'],0)
            self.assertEqual(step['state'],'PAUSED')


if __name__=='__main__': unittest.main()
