"""Opening a finished video by itself (api/routes_video.py auto_open): once, only when it is published, never a stale one, and never in tests."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from audio_translate.api import routes_video

JOB = '12345678-1234-4123-8123-123456789abc'


class AutoOpenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        p = patch.object(routes_video, 'DATA', self.data); p.start(); self.addCleanup(p.stop)
        self.marker = self.data / 'tmp' / JOB / 'working' / 'video-open.pending'
        self.marker.parent.mkdir(parents=True); self.marker.write_text(JOB)
        self.video = self.data / 'video.mp4'; self.video.write_bytes(b'x')
        self.opened = []
        p = patch.object(routes_video, 'open_path', lambda path, folder=False: self.opened.append(path)); p.start(); self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'AUDIO_VIDEO_AUTO_OPEN': '1'}); p.start(); self.addCleanup(p.stop)

    def test_a_published_video_opens_once(self):
        with patch.object(routes_video, 'video_file', return_value=self.video):
            self.assertEqual(routes_video.auto_open(), [JOB])
            self.assertEqual(routes_video.auto_open(), [])
        self.assertEqual(self.opened, [self.video]); self.assertFalse(self.marker.exists())

    def test_a_video_not_published_yet_waits_for_the_next_call(self):
        with patch.object(routes_video, 'video_file', return_value=None): self.assertEqual(routes_video.auto_open(), [])
        self.assertTrue(self.marker.exists())
        with patch.object(routes_video, 'video_file', return_value=self.video): self.assertEqual(routes_video.auto_open(), [JOB])

    def test_an_old_marker_is_dropped_without_opening(self):
        old = time.time() - 3600; os.utime(self.marker, (old, old))
        with patch.object(routes_video, 'video_file', return_value=self.video): self.assertEqual(routes_video.auto_open(), [])
        self.assertEqual(self.opened, []); self.assertFalse(self.marker.exists())

    def test_tests_can_turn_it_off(self):
        with patch.dict(os.environ, {'AUDIO_VIDEO_AUTO_OPEN': '0'}), patch.object(routes_video, 'video_file', return_value=self.video):
            self.assertEqual(routes_video.auto_open(), [])
        self.assertTrue(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
