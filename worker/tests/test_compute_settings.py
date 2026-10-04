import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audio_translate.core import compute_settings as compute
from audio_translate.core.storage import atomic_json, read_json
from audio_translate.translation.translation_server import DEFAULTS


class ComputeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.job = self.root / 'job'
        atomic_json(self.job / 'job.json', {'id':'fixture', 'status':'QUEUED'})
        override = patch.object(compute, 'CONFIG', self.root / 'settings' / 'compute.json')
        override.start()
        self.addCleanup(override.stop)

    def test_default_cpu_and_setting_survives_new_read(self):
        self.assertEqual(compute.preference(), 'cpu')
        with patch.object(compute, 'capabilities', return_value={}):
            self.assertEqual(compute.command({'action':'set', 'device':'gpu'})['status'], 200)
        self.assertEqual(compute.preference(), 'gpu')

    def test_capture_at_start_and_do_not_change_mid_workflow(self):
        atomic_json(compute.CONFIG, {'device':'gpu'})
        self.assertEqual(compute.freeze(self.job), 'gpu')
        atomic_json(compute.CONFIG, {'device':'cpu'})
        self.assertEqual(compute.freeze(self.job), 'gpu')
        self.assertEqual(read_json(self.job / 'job.json')['compute_device'], 'gpu')

    def test_legacy_started_workflow_retains_cpu(self):
        atomic_json(compute.CONFIG, {'device':'gpu'})
        atomic_json(self.job / 'job.json', {'started_at':'2026-10-04'})
        self.assertEqual(compute.freeze(self.job), 'cpu')

    def test_gpu_validation_checks_only_required_stages(self):
        available = {'transcription':True, 'translation':False, 'tts':True}
        compute.validate('gpu', ['TTS', 'MODERATION'], available)
        with self.assertRaisesRegex(RuntimeError, 'GPU'):
            compute.validate('gpu', ['TRANSCRIPTION', 'TRANSLATION'], available)
        compute.validate('cpu', ['TRANSLATION'], {})

    def test_bad_preference_does_not_overwrite_saved_choice(self):
        atomic_json(compute.CONFIG, {'device':'cpu'})
        self.assertEqual(compute.command({'action':'set', 'device':'auto'})['status'], 400)
        self.assertEqual(compute.preference(), 'cpu')

    def test_adapter_and_stage_devices_are_consistent(self):
        from audio_translate.translation.hymt_translation import default_settings
        settings = {'translation':default_settings(), 'tts':{'device':'cpu', 'voice':'fixture'}}
        compute.apply_adapters(settings, 'gpu')
        self.assertEqual(settings['translation']['n_gpu_layers'], 999)
        self.assertEqual(settings['tts']['device'], 'cuda')
        self.assertEqual(compute.stage_environment('gpu')['FUNASR_DEVICE'], 'cuda:0')
        compute.apply_adapters(settings, 'cpu')
        self.assertEqual(settings['translation']['n_gpu_layers'], 0)
        self.assertEqual(settings['tts']['device'], 'cpu')

    def test_saved_adapter_is_updated_from_workflow_not_global_env(self):
        from audio_translate.tts.adapters import adapter_settings
        from audio_translate.translation.hymt_translation import default_settings
        atomic_json(self.job / 'job.json', {'compute_device':'gpu', 'selected_voice_id':'fixture'})
        atomic_json(self.job / 'working' / 'adapters.json',
                    {'translation':default_settings(), 'tts':{'device':'cpu', 'voice':'old'}})
        settings = adapter_settings(self.job)
        self.assertEqual(settings['tts']['voice'], 'fixture')
        self.assertEqual(settings['translation']['device'], 'gpu')
        self.assertEqual(read_json(self.job / 'working' / 'adapters.json')['tts']['device'], 'cuda')

    def test_gpu_auto_bypasses_bundled_cpu_server(self):
        from unittest.mock import MagicMock
        from audio_translate.translation.hymt_translation import TranslationAdapter, default_settings
        model = self.root / 'fixture.gguf'
        model.write_bytes(b'fixture')
        settings = default_settings()
        settings.update(model=str(model), device='gpu', n_gpu_layers=999)
        adapter = TranslationAdapter(settings)
        with patch.object(adapter, 'wait_memory'), patch('audio_translate.core.compute_settings.validate'), \
             patch('audio_translate.translation.translation_server.gpu_memory', return_value={'free':8*1024**3}), \
             patch('llama_cpp.Llama', return_value=MagicMock()) as llama, \
             patch('audio_translate.translation.translation_server.policy', return_value={**DEFAULTS,'engine':'auto'}), \
             patch('audio_translate.translation.translation_server.server_gpu_available', return_value=False), \
             patch('audio_translate.translation.translation_server.Runtime') as runtime:
            adapter.load()
            runtime.assert_not_called()
            self.assertEqual(llama.call_args.kwargs['n_gpu_layers'], 999)
            self.assertNotIn('vocab_only', llama.call_args.kwargs)
            adapter.close()

    def test_unsupported_gpu_fails_before_loading_a_stage(self):
        from audio_translate.workflow.orchestrator import run_stage
        atomic_json(self.job / 'job.json', {'compute_device':'gpu'})
        with patch('audio_translate.core.license_gate.assert_allowed'), \
             patch.object(compute, 'capabilities', return_value={}), \
             patch('shutil.which') as binary:
            with self.assertRaisesRegex(RuntimeError, 'GPU'):
                run_stage(self.job, 'transcription')
            binary.assert_not_called()

    def test_gpu_shared_server_requires_cuda_helper(self):
        from unittest.mock import MagicMock
        from audio_translate.translation.hymt_translation import TranslationAdapter, default_settings
        model=self.root/'fixture.gguf';model.write_bytes(b'fixture')
        binary=self.root/'server.exe';binary.write_bytes(b'fixture')
        settings=default_settings();settings.update(model=str(model),device='gpu',n_gpu_layers=999)
        adapter=TranslationAdapter(settings)
        with (patch.object(adapter,'wait_memory'),patch('audio_translate.core.compute_settings.validate'),
              patch('audio_translate.translation.translation_server.gpu_memory',return_value={'free':8*1024**3}),
              patch('llama_cpp.Llama',return_value=MagicMock()) as llama,
              patch('audio_translate.translation.translation_server.policy',return_value={**DEFAULTS,'engine':'server'}),
              patch('audio_translate.translation.translation_server.executable',return_value=binary),
              patch('audio_translate.translation.translation_server.server_gpu_available',return_value=True),
              patch('audio_translate.translation.translation_server.Runtime') as runtime):
            adapter.load()
            self.assertTrue(llama.call_args.kwargs['vocab_only'])
            runtime.return_value.start.assert_called_once()
            adapter.close()

    def test_explicit_gpu_server_rejects_cpu_only_helper(self):
        from audio_translate.translation.hymt_translation import TranslationAdapter, default_settings
        model=self.root/'fixture.gguf';model.write_bytes(b'fixture')
        settings=default_settings();settings.update(model=str(model),device='gpu',n_gpu_layers=999)
        adapter=TranslationAdapter(settings)
        with (patch.object(adapter,'wait_memory'),patch('audio_translate.core.compute_settings.validate'),
              patch('audio_translate.translation.translation_server.gpu_memory',return_value={'free':8*1024**3}),
              patch('audio_translate.translation.translation_server.policy',return_value={**DEFAULTS,'engine':'server'}),
              patch('audio_translate.translation.translation_server.server_gpu_available',return_value=False)):
            with self.assertRaisesRegex(RuntimeError,'CUDA-enabled'):adapter.load()

    def test_gpu_error_belongs_to_standalone_tool_stage(self):
        from audio_translate.workflow.orchestrator import run
        atomic_json(self.job / 'job.json', {'compute_device':'gpu', 'tool_steps':['TTS']})
        with patch('audio_translate.core.license_gate.assert_allowed'), \
             patch.object(compute, 'capabilities', return_value={}), \
             patch('audio_translate.workflow.orchestrator.record_failure') as failure:
            self.assertEqual(run(self.job), 1)
            self.assertEqual(failure.call_args.args[1], 'TTS')


if __name__ == '__main__': unittest.main()
