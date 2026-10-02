"""Profile isolation, cookie rotation, API secrecy and resume regression checks."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import youtube_session as session
from errors import classify
from storage import atomic_json


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'YOUTUBE_SESSION_ROOT': self.temp.name, 'YTDLP_COOKIES_FILE': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_domain_expiration_and_http_only_are_preserved(self):
        raw = [dict(name='SID', value='test-secret', domain='.youtube.com', path='/', secure=True, httpOnly=True, expires=time.time()+3600),
               dict(name='other', value='secret', domain='.google.com'),
               dict(name='other', value='secret', domain='notyoutube.com'),
               dict(name='other', value='secret', domain='youtube.com.evil.test'),
               dict(name='expired', value='secret', domain='.youtube.com', expires=time.time()-1),
               dict(name='session', value='session', domain='www.youtube.com', expires=-1)]
        cookies = session.cookie_objects(raw)
        self.assertEqual([c.name for c in cookies], ['SID', 'session'])
        self.assertTrue(cookies[0].secure)
        self.assertIn('HttpOnly', cookies[0]._rest)
        self.assertTrue(cookies[1].discard)
        self.assertIsNone(cookies[1].expires)

    def test_login_browser_has_no_debugging_or_automation_flags(self):
        with patch.object(session,'browser_binary',return_value='browser.exe'),patch.object(session.subprocess,'Popen') as process,patch.object(session,'live_endpoint') as endpoint:
            url,_=session.launch(True)
        self.assertIsNone(url);endpoint.assert_not_called()
        args=process.call_args.args[0]
        self.assertFalse(any('remote-debugging' in arg or 'headless' in arg or 'disable-blink' in arg or 'enable-automation' in arg for arg in args))
        self.assertEqual(session.configuration()['browser_mode'],'manual')

    def test_manual_login_must_be_closed_before_cookie_reader_launches(self):
        session.save_state(enabled=True)
        with patch.object(session,'live_endpoint',return_value=None),patch.object(session,'manual_profile_running',return_value=True),patch.object(session,'launch') as launch:
            with self.assertRaises(session.YouTubeSessionError):session.cookies_for_download()
        launch.assert_not_called();self.assertEqual(session.status()['state'],'CLOSE_LOGIN_WINDOW')

    def test_old_interactive_debug_login_is_not_automated_or_closed(self):
        session.save_state(enabled=True,browser_mode='interactive')
        with patch.object(session,'live_endpoint',return_value='ws://127.0.0.1:9222/devtools/browser/abc'),patch.object(session,'command') as command,patch.object(session,'launch') as launch:
            with self.assertRaises(session.YouTubeSessionError):session.open_login()
        command.assert_not_called();launch.assert_not_called()

    def test_process_detection_only_matches_dedicated_profile(self):
        import psutil
        unrelated=Mock(info={'cmdline':['chrome.exe','--user-data-dir='+str(Path(self.temp.name)/'personal')]})
        own=Mock(info={'cmdline':['msedge.exe','--user-data-dir='+str(Path(self.temp.name)/'profile')]})
        with patch.object(psutil,'process_iter',return_value=[unrelated]):self.assertFalse(session.manual_profile_running())
        with patch.object(psutil,'process_iter',return_value=[unrelated,own]):self.assertTrue(session.manual_profile_running())

    def test_cdp_port_file_rejects_nonlocal_or_invalid_targets(self):
        profile = Path(self.temp.name)/'profile'
        profile.mkdir()
        for content in ('80\n/devtools/browser/abc', '9222\n//evil.test/browser', '9222\n/devtools/page/abc', 'invalid'):
            (profile/'DevToolsActivePort').write_text(content)
            self.assertIsNone(session.endpoint())
        (profile/'DevToolsActivePort').write_text('9222\n/devtools/browser/123-abcd')
        self.assertEqual(session.endpoint(), 'ws://127.0.0.1:9222/devtools/browser/123-abcd')

    @contextmanager
    def fake_socket(self, _url):
        yield Mock()

    def test_each_download_reads_rotated_cookie_and_never_persists_values(self):
        session.save_state(enabled=True, state='SESSION_SAVED')
        for value in ('first-secret', 'rotated-secret'):
            with patch.object(session, 'live_endpoint', return_value='ws://127.0.0.1:9222/devtools/browser/abc'), \
                 patch.object(session, 'socket_for', self.fake_socket), patch.object(session, 'refresh_page'), \
                 patch.object(session, 'command', return_value={'cookies': [dict(name='SID', value=value, domain='.youtube.com', expires=time.time()+3600)]}):
                self.assertEqual(session.cookies_for_download()[0].value, value)
                self.assertNotIn(value, json.dumps(session.status()))
                self.assertNotIn(value, (Path(self.temp.name)/'connection.json').read_text())
        self.assertEqual(session.status()['state'], 'SESSION_SAVED')

    def test_missing_session_requires_relogin_and_disabled_keeps_guest_mode(self):
        self.assertIsNone(session.cookies_for_download())
        session.save_state(enabled=True)
        with patch.object(session, 'live_endpoint', return_value='ws://127.0.0.1:9222/devtools/browser/abc'), \
             patch.object(session, 'socket_for', self.fake_socket), patch.object(session, 'refresh_page'), \
             patch.object(session, 'command', return_value={'cookies': []}):
            with self.assertRaises(session.YouTubeSessionError) as error:
                session.cookies_for_download()
        self.assertEqual(classify(error.exception), 'YOUTUBE_AUTH')
        self.assertEqual(session.status()['state'], 'SIGN_IN_REQUIRED')

    def test_disconnect_and_upgrade_preserve_profile(self):
        profile = Path(self.temp.name)/'profile'
        profile.mkdir()
        (profile/'Local State').write_text('browser-managed-state')
        session.save_state(enabled=True, state='SESSION_SAVED')
        with patch.object(session, 'live_endpoint', return_value=None):
            session.disconnect()
        self.assertFalse(session.status()['enabled'])
        self.assertTrue((profile/'Local State').exists())
        with patch.dict(os.environ, {'AUDIO_DATA_DIR': self.temp.name+'/different-release-data'}):
            self.assertEqual(session.session_root(), Path(self.temp.name))

    def test_completed_download_never_opens_browser_or_changes_input(self):
        from pipeline import download
        job = Path(self.temp.name)/'job'
        (job/'source').mkdir(parents=True)
        audio = job/'source'/'audio.webm'
        audio.write_bytes(b'completed-audio')
        with patch.object(session, 'cookies_for_download') as cookies:
            self.assertEqual(download(job), audio)
            cookies.assert_not_called()
        self.assertEqual(audio.read_bytes(), b'completed-audio')

    def test_worker_injects_profile_cookie_instead_of_stale_legacy_file(self):
        from pipeline import download
        job = Path(self.temp.name)/'job'
        (job/'source').mkdir(parents=True)
        (job/'working').mkdir()
        atomic_json(job/'job.json', {'url': 'https://youtu.be/abcdefghijk', 'name': 'test'})
        cookie = session.cookie_objects([dict(name='SID', value='profile-secret', domain='.youtube.com', expires=-1)])[0]
        ydl = Mock()
        def extract(_url, download):
            (job/'source'/'audio.webm').write_bytes(b'audio')
            return {'vcodec': 'none', 'duration': 5}
        ydl.extract_info.side_effect = extract
        with patch('license_gate.assert_allowed'), patch.object(session, 'cookies_for_download', return_value=[cookie]), \
             patch('yt_dlp.YoutubeDL') as factory, patch.dict(os.environ, {'YTDLP_COOKIES_FILE': 'nonexistent-stale-cookie'}):
            factory.return_value.__enter__.return_value = ydl
            download(job)
            self.assertNotIn('cookiefile', factory.call_args.args[0])
            ydl.cookiejar.set_cookie.assert_called_once_with(cookie)


if __name__ == '__main__':
    unittest.main()
