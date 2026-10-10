"""The app's YouTube browser must not pile up tabs or stay in memory: process identification, launch flags, leftovers, the close button.

The last class uses a real Edge/Chrome on a throwaway profile (skipped when there is none, or when RUN_BROWSER_CLEANUP=0).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import Mock, patch

from audio_translate.transcription import browser_cleanup as cleanup
from audio_translate.transcription import youtube_session as session


def fake(profile, *extra, pid=1):
    return Mock(pid=pid, info={'cmdline': ['msedge.exe', f'--user-data-dir={profile}', *extra]})


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'YOUTUBE_SESSION_ROOT': self.temp.name, 'YTDLP_COOKIES_FILE': ''}); env.start(); self.addCleanup(env.stop)
        self.profile = Path(self.temp.name) / 'profile'


class IdentificationTests(Base):
    def run_with(self, processes, function):
        import psutil
        with patch.object(psutil, 'process_iter', return_value=processes): return function()

    def test_only_the_apps_own_profile_is_matched(self):
        own = fake(self.profile, '--headless=new', pid=1)
        other = fake(Path(self.temp.name) / 'personal', '--headless=new', pid=2)
        plain = Mock(pid=3, info={'cmdline': ['msedge.exe']})
        self.assertEqual([p.pid for p in self.run_with([own, other, plain], cleanup.profile_processes)], [1])
        self.assertEqual([p.pid for p in self.run_with([other, plain], cleanup.hidden_processes)], [])

    def test_a_hidden_browser_is_taken_with_its_children_but_a_sign_in_window_is_never(self):
        main = fake(self.profile, '--headless=new', pid=1)
        renderer = fake(self.profile, '--type=renderer', pid=2)
        gpu = fake(self.profile, '--type=gpu-process', '--headless', pid=3)
        self.assertEqual(sorted(p.pid for p in self.run_with([main, renderer, gpu], cleanup.hidden_processes)), [1, 2, 3])
        window = fake(self.profile, pid=4)
        window_child = fake(self.profile, '--type=renderer', pid=5)
        self.assertEqual(self.run_with([window, window_child], cleanup.hidden_processes), [])
        self.assertEqual([p.pid for p in self.run_with([window, window_child], cleanup.window_processes)], [4])
        self.assertEqual(self.run_with([window, window_child], cleanup.running), {'hidden': 0, 'window': True})
        self.assertEqual(self.run_with([main, renderer], cleanup.running), {'hidden': 2, 'window': False})

    def test_stop_asks_first_then_kills_what_is_left(self):
        import psutil
        polite, stubborn = Mock(), Mock()
        with patch.object(psutil, 'wait_procs', side_effect=[([polite], [stubborn]), ([stubborn], [])]):
            self.assertEqual(cleanup.stop([polite, stubborn]), 2)
        polite.terminate.assert_called_once(); stubborn.terminate.assert_called_once(); stubborn.kill.assert_called_once(); polite.kill.assert_not_called()

    def test_close_window_sends_a_close_request_not_a_kill(self):
        import psutil
        window = fake(self.profile, pid=44)
        calls = []
        with patch.object(psutil, 'process_iter', side_effect=[[window], []]), \
             patch.object(psutil, 'wait_procs', return_value=([], [])), \
             patch.object(cleanup.subprocess, 'run', side_effect=lambda *a, **k: calls.append(a[0])):
            self.assertTrue(cleanup.close_window())
        self.assertEqual(calls, [['taskkill', '/PID', '44']])   # no /F: Edge saves its session
        window.kill.assert_not_called(); window.terminate.assert_not_called()


class CompatLayerTests(Base):
    """Windows gives the app __COMPAT_LAYER=DetectorsAppHealth; Edge then restarts itself and the first process exits at once."""
    def test_the_browser_never_sees_the_compat_layer_variable(self):
        with patch.dict(os.environ, {'__COMPAT_LAYER': 'DetectorsAppHealth', 'KEEP_ME': '1'}):
            env = cleanup.browser_env()
        self.assertNotIn('__COMPAT_LAYER', env); self.assertEqual(env['KEEP_ME'], '1')

    def test_a_first_process_that_hands_over_and_exits_is_not_a_failure(self):
        first = Mock(); first.poll.return_value = 0            # exited at once
        answers = iter([None, None, None, 'ws://127.0.0.1:1/devtools/browser/x'])
        with patch.object(session, 'browser_binary', return_value='browser.exe'), patch.object(cleanup, 'start_hidden', return_value=first), \
             patch.object(cleanup, 'hidden_processes', return_value=[Mock()]), patch.object(session, 'live_endpoint', side_effect=lambda: next(answers)), \
             patch.object(session.time, 'sleep'):
            self.assertEqual(session.launch(False)[0], 'ws://127.0.0.1:1/devtools/browser/x')
        with patch.object(session, 'browser_binary', return_value='browser.exe'), patch.object(cleanup, 'start_hidden', return_value=first), \
             patch.object(cleanup, 'hidden_processes', return_value=[]), patch.object(session, 'live_endpoint', return_value=None), \
             patch.object(cleanup, 'stop_hidden'):
            with self.assertRaises(session.YouTubeSessionError): session.launch(False)   # nothing left of it: a real failure


class LaunchAndLeftoverTests(Base):
    def launch(self, interactive):
        with patch.object(session, 'browser_binary', return_value='browser.exe'), patch.object(session.subprocess, 'Popen') as popen, \
             patch.object(cleanup, 'start_hidden') as hidden, patch.object(session, 'live_endpoint', return_value='ws://127.0.0.1:1/devtools/browser/x'):
            hidden.return_value = Mock()
            session.launch(interactive)
        return (popen.call_args.args[0] if popen.called else None), (hidden.call_args.args[0] if hidden.called else None)

    def test_neither_browser_restores_the_previous_session(self):
        window, none = self.launch(True)
        _, hidden = self.launch(False)
        self.assertNotIn('--restore-last-session', window); self.assertIsNone(none)
        self.assertNotIn('--restore-last-session', hidden)
        self.assertEqual(window[-1], 'https://www.youtube.com/')

    def test_the_hidden_browser_has_no_extensions_and_is_started_through_the_job_helper_the_window_is_not(self):
        window, _ = self.launch(True)
        _, hidden = self.launch(False)
        self.assertIn('--disable-extensions', hidden); self.assertIn('--headless=new', hidden); self.assertEqual(hidden[-1], 'about:blank')
        self.assertNotIn('--disable-extensions', window)       # the person's sign-in window keeps Edge's normal behaviour
        self.assertFalse(any('headless' in a or 'remote-debugging' in a for a in window))

    def test_a_leftover_hidden_browser_is_ended_before_a_new_one_starts_and_the_new_one_is_always_ended(self):
        session.save_state(enabled=True)
        order = []
        owned = Mock(); owned.wait.side_effect = lambda **k: order.append('wait')
        with patch.object(session, 'close_hidden', side_effect=lambda: order.append('close leftover') or 1), \
             patch.object(session, 'manual_profile_running', return_value=False), \
             patch.object(session, 'launch', side_effect=lambda hidden: order.append('launch') or ('ws://127.0.0.1:1/devtools/browser/x', owned)), \
             patch.object(session, 'refresh_page', side_effect=RuntimeError('page failed')), \
             patch.object(session, 'socket_for') as sock, patch.object(cleanup, 'stop_hidden', side_effect=lambda: order.append('stop hidden')):
            with self.assertRaises(session.YouTubeSessionError): session.cookies_for_download()
        self.assertEqual(order[:2], ['close leftover', 'launch'])
        self.assertEqual(order[-2:], ['wait', 'stop hidden'])   # even after a failure, nothing of the new browser stays behind
        sock.assert_called()                                    # Browser.close was sent

    def test_close_browser_ends_the_hidden_one_and_reports_a_window_that_stays_open(self):
        with patch.object(session, 'close_hidden') as hidden, patch.object(cleanup, 'window_processes', return_value=[Mock()]), \
             patch.object(cleanup, 'close_window', return_value=False), patch.object(session, 'browser_running', return_value={'hidden': 0, 'window': True}):
            result = session.close_browser()
        hidden.assert_called_once(); self.assertTrue(result['window_open'])
        with patch.object(session, 'close_hidden'), patch.object(cleanup, 'window_processes', return_value=[]), \
             patch.object(cleanup, 'close_window') as close:
            self.assertFalse(session.close_browser()['window_open']); close.assert_not_called()

    def test_status_tells_the_settings_page_whether_anything_is_running(self):
        with patch.object(cleanup, 'running', return_value={'hidden': 3, 'window': False}):
            self.assertEqual(session.status()['browser_running'], {'hidden': 3, 'window': False})
        with patch.object(cleanup, 'running', side_effect=OSError): self.assertIsNone(session.status()['browser_running'])


@unittest.skipIf(os.getenv('RUN_BROWSER_CLEANUP') == '0' or not session.browser_binary(), 'needs Edge or Chrome')
class RealBrowserTests(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(lambda: cleanup.stop(cleanup.profile_processes()))

    def pages(self, url):
        with session.socket_for(url) as ws:
            return [t for t in session.command(ws, 'Target.getTargets')['targetInfos'] if t['type'] == 'page']

    def test_refresh_reuses_the_blank_tab_and_repeated_launches_do_not_add_tabs(self):
        counts = []
        for _ in range(3):
            url, process = session.launch(False)
            try:
                counts.append(len(self.pages(url)))
                session.refresh_page(url, page='data:text/html,<title>t</title>')
                counts.append(len(self.pages(url)))
                self.assertEqual(self.pages(url)[0]['url'], 'about:blank')   # left blank again
            finally:
                session.close_hidden()
                process.wait(timeout=10)
            self.assertEqual(cleanup.hidden_processes(), [])
        self.assertEqual(counts, [1] * 6)

    def test_launch_works_when_the_app_runs_under_the_compat_layer(self):
        """Before the fix: 3/3 launches failed in 0.4 s with this variable."""
        with patch.dict(os.environ, {'__COMPAT_LAYER': 'DetectorsAppHealth'}):
            for _ in range(2):
                url, process = session.launch(False)
                self.assertTrue(session.live_endpoint())
                session.close_hidden(); process.wait(timeout=10)
                self.assertEqual(cleanup.profile_processes(), [])

    def test_killing_the_python_that_started_the_browser_ends_the_browser(self):
        """The leak behind the memory problem: a worker stopped mid-download left Edge (16 processes) behind."""
        code = textwrap.dedent('''
            import os, sys, time
            sys.path.insert(0, sys.argv[1])
            from audio_translate.transcription import youtube_session as s
            s.launch(False); print('READY', flush=True); time.sleep(120)
        ''')
        worker = Path(__file__).resolve().parents[1]
        child = subprocess.Popen([sys.executable, '-c', code, str(worker)], stdout=subprocess.PIPE, text=True,
                                 env={**os.environ, 'YOUTUBE_SESSION_ROOT': self.temp.name, 'PYTHONUTF8': '1'})
        try:
            self.assertEqual(child.stdout.readline().strip(), 'READY')
            self.assertTrue(cleanup.hidden_processes())
        finally:
            child.kill(); child.wait(timeout=10)
        for _ in range(50):
            if not cleanup.profile_processes(): break
            time.sleep(.2)
        self.assertEqual(cleanup.profile_processes(), [])

    def test_a_leftover_hidden_browser_is_removed_by_the_next_check_and_by_the_close_button(self):
        session.save_state(enabled=True)
        url, process = session.launch(False)           # the leftover: nobody will close it
        self.assertTrue(cleanup.hidden_processes())
        with patch.object(session, 'refresh_page'):
            with self.assertRaises(session.YouTubeSessionError): session.cookies_for_download()   # not signed in: raises, but must clean up
        self.assertEqual(cleanup.profile_processes(), [])
        process.wait(timeout=10)
        _, process = session.launch(False)
        self.assertTrue(session.browser_running()['hidden'])
        self.assertFalse(session.close_browser()['window_open'])
        process.wait(timeout=10)
        self.assertEqual(cleanup.profile_processes(), [])


if __name__ == '__main__':
    unittest.main()
