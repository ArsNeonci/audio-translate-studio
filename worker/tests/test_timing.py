"""The timing log of a Convert click: one line per click, slow ones marked, capped, never breaking the click."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_translate.api import timing


class TimingTests(unittest.TestCase):
    def test_a_click_is_logged_with_its_steps_and_a_slow_one_is_marked(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(timing, 'DATA', Path(folder)):
            watch = timing.Stopwatch(); watch.mark('licence'); watch.mark('storage')
            timing.log('create', watch, {'licence': 5, 'created': 40}, outcome=200)
            slow = timing.Stopwatch(); slow.start -= 5; slow.mark('worker')
            timing.log('create', slow, None, outcome=200)
            rows = [json.loads(line) for line in (Path(folder) / 'timing.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['route'] for r in rows], ['create', 'create'])
            self.assertEqual(set(rows[0]['steps_ms']), {'licence', 'storage'})
            self.assertEqual(rows[0]['worker_ms']['created'], 40)
            self.assertNotIn('slow', rows[0]); self.assertTrue(rows[1]['slow'])

    def test_the_log_is_capped_and_a_failure_to_write_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(timing, 'DATA', Path(folder)), patch.object(timing, 'LIMIT', 2000):
            for _ in range(60): timing.log('create', timing.Stopwatch())
            self.assertLess((Path(folder) / 'timing.jsonl').stat().st_size, 4000)
        with patch.object(timing, 'DATA', Path('Z:/no/such/drive')): timing.log('create', timing.Stopwatch())   # no exception


if __name__ == '__main__':
    unittest.main()
