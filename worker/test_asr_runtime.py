import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import asr_runtime as runtime
from storage import atomic_json, read_json
from control import Cancelled


def generous():
    return {'physical_cores':8,'logical_cores':16,'total':16*runtime.GIB,
            'available':10*runtime.GIB,'cpu':10,'plugged':True,'hot':False,'thermal_available':False}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.job=Path(self.temp.name);(self.job/'working').mkdir()
        atomic_json(self.job/'job.json',{'status':'TRANSCRIBING','duration_ms':4000})
        for target in ('license_gate.assert_allowed','pipeline.update','storage.progress'):
            mock=patch(target,return_value=None); value=mock.start();self.addCleanup(mock.stop)
            if target=='storage.progress': self.progress=value
        self.chunks=[{'start':i*1000,'end':(i+1)*1000,'own_start':i*1000,'own_end':(i+1)*1000} for i in range(4)]
        self.profile={'workers':2,'threads':3,'single_threads':6,'peak_bytes':runtime.GIB}

    def test_budget_cpu_ram_battery_heat(self):
        self.assertTrue(runtime.may_add(generous(),runtime.GIB))
        for changes in ({'available':4*runtime.GIB},{'cpu':90},{'hot':True},{'plugged':False,'cpu':70}):
            self.assertFalse(runtime.may_add({**generous(),**changes},runtime.GIB))
        self.assertEqual(runtime.reserve(8*runtime.GIB),3*runtime.GIB)
        self.assertEqual(runtime.reserve(32*runtime.GIB),int(6.4*runtime.GIB))

    def test_out_of_order_single_writer_and_resume(self):
        cached=self.job/'working'/'chunk-000001.json'
        atomic_json(cached,[{'start_ms':1000,'end_ms':2000,'text':'cached'}]);before=cached.read_bytes()
        chunks=[dict(chunk) for chunk in self.chunks];chunks[0]['test_delay']=1;chunks[2]['test_delay']=.03
        production=lambda:((i,[0],chunks[i]) for i in (0,2,3))
        with patch('asr_runtime.hardware',side_effect=generous),patch.dict('os.environ',{'ASR_SCALE_UP_SECONDS':'0'}):
            runtime.run(self.job,None,chunks,self.profile,fake=True,producer_override=production)
        self.assertEqual(cached.read_bytes(),before)
        self.assertTrue(all(runtime.checkpoint(self.job/'working'/f'chunk-{i:06d}.json') for i in range(4)))
        counts=[call.args[3] for call in self.progress.call_args_list]
        self.assertEqual(counts,[1,2,3,4])
        self.assertEqual(read_json(self.job/'job.json')['status'],'TRANSCRIBING')

    def test_complete_cache_never_loads_model_or_decodes(self):
        for i in range(4): atomic_json(self.job/'working'/f'chunk-{i:06d}.json',[])
        with patch('asr_runtime.Pool') as pool,patch('pipeline.decoder') as decode:
            runtime.run(self.job,None,self.chunks)
        pool.assert_not_called();decode.assert_not_called()

    def test_pause_drains_assigned_chunk_and_does_not_dispatch_next(self):
        chunks=[{**chunk,'test_delay':.2} for chunk in self.chunks]
        original=runtime.Pool.submit
        def submit(pool,member,task):
            original(pool,member,task)
            atomic_json(self.job/'working'/'cancel.signal',{'mode':'pause'})
        production=lambda:((i,[0],chunks[i]) for i in range(4))
        with patch('asr_runtime.hardware',side_effect=generous),patch.object(runtime.Pool,'submit',autospec=True,side_effect=submit),self.assertRaises(Cancelled):
            runtime.run(self.job,None,chunks,{**self.profile,'workers':1},fake=True,producer_override=production)
        self.assertTrue(runtime.checkpoint(self.job/'working'/'chunk-000000.json'))
        self.assertFalse((self.job/'working'/'chunk-000001.json').exists())
        self.assertEqual(self.progress.call_args.args[3],1)

    def test_failure_keeps_completed_checkpoints(self):
        chunks=[dict(chunk) for chunk in self.chunks];chunks[2]['test_fail']=True
        production=lambda:((i,[0],chunks[i]) for i in range(4))
        with patch('asr_runtime.hardware',side_effect=generous),self.assertRaises(RuntimeError):
            runtime.run(self.job,None,chunks,{**self.profile,'workers':1},fake=True,producer_override=production)
        self.assertTrue(runtime.checkpoint(self.job/'working'/'chunk-000000.json'))
        self.assertTrue(runtime.checkpoint(self.job/'working'/'chunk-000001.json'))

    def test_cancel_signal_exits_without_starting_pool(self):
        atomic_json(self.job/'working'/'cancel.signal',{})
        with self.assertRaises(Cancelled): runtime.wait_memory(self.job,runtime.GIB,'TEST')

    def test_memory_wait_is_cancellable(self):
        with patch('asr_runtime.hardware',return_value={**generous(),'available':runtime.GIB}),patch('asr_runtime.time.sleep',side_effect=lambda _:atomic_json(self.job/'working'/'cancel.signal',{})):
            with self.assertRaises(Cancelled):runtime.wait_memory(self.job,runtime.GIB,'TEST')
        self.assertEqual(read_json(self.job/'working'/'asr-runtime.json')['state'],'WAITING_MEMORY')

    def test_measured_calibration_has_no_checkpoint_writes(self):
        chunks=[{**chunk,'test_delay':.04} for chunk in self.chunks]
        samples=[(i,[0],chunk) for i,chunk in enumerate(chunks)]
        first,baseline=runtime.measure(self.job,samples,4,1,4,fake=True)
        second,outputs=runtime.measure(self.job,samples,4,2,3,baseline,fake=True)
        self.assertTrue(second['compatible']);self.assertEqual(outputs,baseline)
        self.assertGreater(first['seconds'],0);self.assertGreater(second['peak_bytes'],0)
        self.assertFalse(list((self.job/'working').glob('chunk-*.json')))

    def test_quality_guard_and_corrupt_cache(self):
        row={'text':'你好。','start_ms':0,'end_ms':1000}
        self.assertTrue(runtime.same_output([row],[{**row,'start_ms':10}]))
        self.assertFalse(runtime.same_output([row],[{**row,'text':'different'}]))
        self.assertFalse(runtime.same_output([row],[{**row,'end_ms':1100}]))
        path=self.job/'working'/'chunk-000000.json';path.write_text('broken',encoding='utf-8')
        self.assertFalse(runtime.checkpoint(path))


if __name__=='__main__':unittest.main()
