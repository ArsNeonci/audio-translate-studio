"""Opt-in real browser test using a new isolated profile and synthetic cookies only."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from audio_translate.transcription import browser_cleanup as cleanup
from audio_translate.transcription import youtube_session as session


def cookie(name, value, domain='.youtube.com'):
    return {'name': name, 'value': value, 'domain': domain, 'path': '/', 'secure': True, 'expires': time.time() + 3600}


@unittest.skipUnless(os.getenv('RUN_YOUTUBE_BROWSER_SMOKE') == '1', 'Opt-in isolated Edge/Chrome integration test')
class BrowserTests(unittest.TestCase):
    def store(self, cookies):
        """Put synthetic cookies into the profile through a hidden browser, then close it so they are written to disk."""
        url, process = session.launch(False)
        try:
            with session.socket_for(url) as ws:
                session.command(ws, 'Storage.setCookies', {'cookies': cookies})
        finally:
            session.close_hidden()

    def test_persist_rotate_and_close_owned_browser(self):
        with tempfile.TemporaryDirectory(prefix='audio-youtube-smoke-') as directory, \
             patch.dict(os.environ, {'YOUTUBE_SESSION_ROOT': directory}), \
             patch.object(session, 'refresh_page'):
            try:
                session.save_state(enabled=True)
                self.store([cookie('SID', 'synthetic-test-only'), cookie('unrelated', 'never-export', '.example.com')])
                first = session.cookies_for_download()          # starts its own browser, reads the saved profile, closes it
                self.assertEqual([c.name for c in first], ['SID'])
                self.assertEqual(first[0].value, 'synthetic-test-only')
                self.assertEqual(cleanup.profile_processes(), [])
                self.store([cookie('SID', 'synthetic-rotated')])
                self.assertEqual(session.cookies_for_download()[0].value, 'synthetic-rotated')
                self.assertIsNone(session.live_endpoint())
                self.assertEqual(cleanup.profile_processes(), [])
                self.assertTrue((Path(directory) / 'profile' / 'Default').is_dir())
                self.assertNotIn('synthetic-rotated', (Path(directory) / 'connection.json').read_text())
            finally:
                cleanup.stop(cleanup.profile_processes())


if __name__ == '__main__':
    unittest.main()
