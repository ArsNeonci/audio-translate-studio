"""The free RAM a translation waits for (core/translation_memory.py): the slider's range, the default for one slot, that the shipped policy follows it,
and that a workflow already waiting for memory starts when the slider is lowered, without any restart."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from audio_translate.core import translation_memory as tm
from audio_translate.translation import translation_server
from audio_translate.translation.hymt_translation import TranslationAdapter


class Memory:
    def __init__(self, available_gib): self.available = int(available_gib * 1024 ** 3); self.total = 16 * 1024 ** 3


class TranslationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        patcher = patch.object(tm, 'CONFIG', Path(self.temp.name) / 'settings' / 'translation-memory.json'); patcher.start(); self.addCleanup(patcher.stop)

    def test_the_default_is_what_one_slot_needs(self):
        self.assertEqual((tm.saved_gib(), tm.effective_gib(), tm.DEFAULT_GIB), (None, 5.5, 5.5))
        self.assertEqual(translation_server.policy()['start_free_gib'], 5.5)
        status = tm.status()
        self.assertEqual((status['min_gib'], status['max_gib'], status['step_gib'], status['customised']), (4.0, 8.0, 0.5, False))

    def test_the_range_and_the_step(self):
        for good in (4, 4.0, 4.5, 6, 7.5, 8):
            self.assertEqual(tm.save(good), float(good)); self.assertEqual(tm.effective_gib(), float(good))
        for bad in (3.5, 8.5, 6.3, 0, -1, '6', None, True, float('nan'), float('inf')):
            with self.assertRaises(ValueError, msg=repr(bad)): tm.save(bad)
        self.assertEqual(tm.effective_gib(), 8.0)                       # a refused value changes nothing

    def test_an_unusable_file_means_the_default_not_a_crash(self):
        tm.CONFIG.parent.mkdir(parents=True)
        for text in ('{', '[]', '{"start_free_gib": 99}', '{"start_free_gib": "6"}', ''):
            tm.CONFIG.write_text(text, encoding='utf-8')
            self.assertIsNone(tm.saved_gib(), text); self.assertEqual(tm.effective_gib(), 5.5)

    def test_the_policy_and_the_admission_follow_the_slider(self):
        tm.save(4.5)
        self.assertEqual(translation_server.policy()['start_free_gib'], 4.5)
        from audio_translate.workflow import workflow_admission
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('HY_MT_STARTUP_AVAILABLE_GIB', None)
            allocation, _, _ = workflow_admission.model_budget(4)
        self.assertEqual(allocation, int(4.5 * 1024 ** 3))
        tm.save(8)
        self.assertEqual(translation_server.policy()['start_free_gib'], 8.0)

    def test_a_workflow_that_is_waiting_starts_when_the_slider_is_lowered(self):
        tm.save(6.0)
        adapter = TranslationAdapter.__new__(TranslationAdapter)
        adapter.job_dir = None; adapter.settings = {'memory_wait_seconds': 60}
        started = []

        def wait():
            adapter.wait_memory(lambda: translation_server.policy()['start_free_gib'], 'MODEL_LOADING'); started.append(time.monotonic())

        with patch('psutil.virtual_memory', return_value=Memory(5.28)), patch('audio_translate.core.memory_policy.commit_available', return_value=None):
            thread = threading.Thread(target=wait, daemon=True); thread.start()
            time.sleep(3)
            self.assertEqual(started, [])                               # 5.28 GiB free, 6 needed: still waiting
            tm.save(5.0)                                                # the person moves the slider
            thread.join(10)
        self.assertEqual(len(started), 1, 'the waiting workflow did not follow the slider')

    def test_the_wait_still_ends_at_the_timeout(self):
        adapter = TranslationAdapter.__new__(TranslationAdapter)
        adapter.job_dir = None; adapter.settings = {'memory_wait_seconds': 1}
        with patch('psutil.virtual_memory', return_value=Memory(2)), patch('audio_translate.core.memory_policy.commit_available', return_value=None):
            with self.assertRaises(RuntimeError): adapter.wait_memory(8, 'MODEL_LOADING')


if __name__ == '__main__':
    unittest.main()
