"""A finished run is not failed because the page was reading lane.json (a display-only file) when the lease ended."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_translate.core import lanes


class LaneCleanupTests(unittest.TestCase):
    def test_a_locked_lane_file_is_retried_and_then_left_alone_never_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder) / 'job'; (job / 'working').mkdir(parents=True)
            (job / 'working' / 'lane.json').write_text('{}')
            real = Path.unlink; calls = []
            def locked(self, missing_ok=False):
                if self.name == 'lane.json' and len(calls) < 3: calls.append(1); raise PermissionError(32, 'in use')
                return real(self, missing_ok=missing_ok)
            lease = lanes.Lease.__new__(lanes.Lease)
            lease.job_dir = job; lease.stop = lanes.threading.Event(); lease.thread = None
            with patch.object(Path, 'unlink', locked), patch.object(lanes, '_Ledger', side_effect=lanes.LockedError()):
                lease.__exit__(None, None, None)
            self.assertEqual(len(calls), 3); self.assertFalse((job / 'working' / 'lane.json').exists())   # busy three times, then removed
            (job / 'working' / 'lane.json').write_text('{}')
            with patch.object(Path, 'unlink', side_effect=PermissionError(32, 'in use')), patch.object(lanes, '_Ledger', side_effect=lanes.LockedError()), patch.object(lanes.time, 'sleep'):
                lease.__exit__(None, None, None)                                                          # always busy: no exception


if __name__ == '__main__':
    unittest.main()
