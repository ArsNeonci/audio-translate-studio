import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audio_translate.core.control import Cancelled
from audio_translate.transcription.transcription_progress import phase, report, load


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory/'working').mkdir()
        (self.directory/'job.json').write_text('unchanged', encoding='utf-8')

    def test_complete_timing_and_no_job_mutation(self):
        with patch('audio_translate.transcription.transcription_progress.now', side_effect=['2026-10-02T00:00:00+00:00', '2026-10-02T00:00:05+00:00']):
            with phase(self.directory, 1):
                report(self.directory, 1, 4, 10)
                self.assertEqual(load(self.directory)['steps'][0]['progress'], 40)
        item = load(self.directory)['steps'][0]
        self.assertEqual((item['state'], item['duration_ms'], item['attempt']), ('COMPLETED', 5000, 1))
        self.assertEqual((self.directory/'job.json').read_text(), 'unchanged')

    def test_failed_retry_accumulates_elapsed(self):
        with patch('audio_translate.transcription.transcription_progress.now', side_effect=['2026-10-02T00:00:00+00:00', '2026-10-02T00:00:02+00:00', '2026-10-02T00:00:04+00:00', '2026-10-02T00:00:07+00:00']):
            with self.assertRaises(ValueError), phase(self.directory, 3):
                raise ValueError('fixture')
            self.assertEqual(load(self.directory)['steps'][2]['state'], 'FAILED')
            with phase(self.directory, 3):
                pass
        item = load(self.directory)['steps'][2]
        self.assertEqual((item['attempt'], item['duration_ms']), (2, 5000))

    def test_cancel_and_cache(self):
        with self.assertRaises(Cancelled), phase(self.directory, 2):
            raise Cancelled()
        self.assertEqual(load(self.directory)['steps'][1]['state'], 'CANCELLED')
        with phase(self.directory, 1, cached=True):
            pass
        item = load(self.directory)['steps'][0]
        self.assertEqual((item['state'], item['attempt'], item['duration_ms']), ('COMPLETED', 0, None))

    def test_legacy_call_does_not_create_telemetry(self):
        report(self.directory, 1, 1, 10)
        self.assertFalse((self.directory/'working'/'transcription-progress.json').exists())


if __name__ == '__main__':
    unittest.main()
