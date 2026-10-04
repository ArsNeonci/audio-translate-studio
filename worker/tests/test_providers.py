import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from audio_translate.core import providers


class ProviderPathsTests(unittest.TestCase):
    def test_flat_default_and_legacy_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flat = root/'VieNeu-TTS-main'
            factory = flat/'src'/'vieneu'/'factory.py'
            factory.parent.mkdir(parents=True)
            factory.touch()
            with patch.object(providers, 'ROOT', root/'app'), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(providers.vieneu_source(), flat)
                self.assertEqual(providers.vieneu_source(flat/'VieNeu-TTS-main'), flat)
                self.assertEqual(providers.vieneu_source(root/'custom'), root/'custom')
                with patch.dict(os.environ, {'VIENEU_SOURCE':str(flat/'VieNeu-TTS-main')}):
                    self.assertEqual(providers.vieneu_source(), flat)

    def test_no_remap_until_flat_runtime_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root/'VieNeu-TTS-main'/'VieNeu-TTS-main'
            with patch.object(providers, 'ROOT', root/'app'):
                self.assertEqual(providers.vieneu_source(legacy), legacy)
