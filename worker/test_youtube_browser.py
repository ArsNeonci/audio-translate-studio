"""Opt-in real browser test using a new isolated profile and synthetic cookies only."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import youtube_session as session


@unittest.skipUnless(os.getenv('RUN_YOUTUBE_BROWSER_SMOKE') == '1', 'Opt-in isolated Edge/Chrome integration test')
class BrowserTests(unittest.TestCase):
    def test_persist_rotate_and_close_owned_browser(self):
        with tempfile.TemporaryDirectory(prefix='audio-youtube-smoke-') as directory, \
             patch.dict(os.environ, {'YOUTUBE_SESSION_ROOT': directory}), \
             patch.object(session, 'refresh_page'):
            session.save_state(enabled=True)
            url, process = session.launch(False)
            try:
                with session.socket_for(url) as ws:
                    session.command(ws, 'Storage.setCookies', {'cookies': [
                        {'name': 'SID', 'value': 'synthetic-test-only', 'domain': '.youtube.com', 'path': '/', 'secure': True, 'expires': time.time()+3600},
                        {'name': 'unrelated', 'value': 'never-export', 'domain': '.example.com', 'path': '/', 'expires': time.time()+3600}]})
                first = session.cookies_for_download()
                self.assertEqual([cookie.name for cookie in first], ['SID'])
                self.assertEqual(first[0].value, 'synthetic-test-only')
                with session.socket_for(url) as ws:
                    session.command(ws, 'Storage.setCookies', {'cookies': [
                        {'name': 'SID', 'value': 'synthetic-rotated', 'domain': '.youtube.com', 'path': '/', 'secure': True, 'expires': time.time()+3600}]})
                self.assertEqual(session.cookies_for_download()[0].value, 'synthetic-rotated')
            finally:
                with session.socket_for(url) as ws:
                    session.command(ws, 'Browser.close')
                process.wait(timeout=10)
            # A new helper must read the saved profile and close itself afterward.
            restored = session.cookies_for_download()
            self.assertEqual(restored[0].value, 'synthetic-rotated')
            self.assertIsNone(session.live_endpoint())
            self.assertTrue((Path(directory)/'profile'/'Default').is_dir())
            self.assertNotIn('synthetic-rotated', (Path(directory)/'connection.json').read_text())


if __name__ == '__main__':
    unittest.main()
