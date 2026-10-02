import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
import voice_previews as previews
from storage import atomic_json, read_json


class FakeAdapter:
    def __init__(self):
        self.settings = {}
        self.calls = []

    def synthesize(self, text, path):
        self.calls.append((self.settings['voice'], text))
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(b'\0\0' * 4800)


class VoicePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('ASSETS', self.root/'assets'), ('DATA', self.root/'data')]:
            mock = patch.object(previews, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.catalog = {'voices':[{'id':'Ngọc Linh'}, {'id':'Hải Đăng'}]}

    def test_builds_once_and_reuses_without_model_calls(self):
        adapter = FakeAdapter()
        self.assertEqual(previews.build(self.catalog, adapter), 2)
        self.assertEqual(adapter.calls, [('Ngọc Linh', 'Tên tôi là Ngọc Linh.'), ('Hải Đăng', 'Tên tôi là Hải Đăng.')])
        manifest = read_json(previews.ASSETS/'manifest.json')
        self.assertEqual(len(manifest['voices']), 2)
        self.assertTrue(all(item['duration_ms'] == 100 for item in manifest['voices']))
        previews.build(self.catalog, adapter)
        self.assertEqual(len(adapter.calls), 2)

    def test_active_workflow_is_untouched_and_blocks_generation(self):
        job = previews.DATA/'tmp'/'fixture'/'job.json'
        atomic_json(job, {'status':'TRANSCRIBING','steps':{'TRANSCRIPTION':{'state':'RUNNING'}}})
        before = job.read_bytes()
        adapter = FakeAdapter()
        self.assertTrue(previews.busy())
        with self.assertRaises(RuntimeError):
            previews.build(self.catalog, adapter)
        self.assertEqual(adapter.calls, [])
        self.assertEqual(job.read_bytes(), before)

    def test_corrupt_cache_regenerated_and_partial_publish_safe(self):
        adapter = FakeAdapter()
        previews.build(self.catalog, adapter)
        manifest = read_json(previews.ASSETS/'manifest.json')
        (previews.ASSETS/f"{manifest['voices'][0]['key']}.wav").write_bytes(b'broken')
        previews.build(self.catalog, adapter)
        self.assertGreater(len(adapter.calls), 2)
        old = (previews.ASSETS/'manifest.json').read_bytes()
        class Failed(FakeAdapter):
            def synthesize(self, text, path):
                path.write_bytes(b'incomplete')
                raise RuntimeError('fixture failure')
        with self.assertRaises(RuntimeError):
            previews.build({'voices':[{'id':'Khác'}]}, Failed())
        self.assertEqual((previews.ASSETS/'manifest.json').read_bytes(), old)
        self.assertFalse(list(previews.ASSETS.glob('*.tmp.wav')))

    def test_terminal_jobs_do_not_block(self):
        atomic_json(previews.DATA/'tmp'/'fixture'/'job.json', {'status':'COMPLETED'})
        self.assertFalse(previews.busy())


if __name__ == '__main__':
    unittest.main()
