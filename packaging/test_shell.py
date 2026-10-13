"""The desktop shell (desktop/, Tauri) starting, watching and ending the local API, on a stand-in installation.

The stand-in has the installed layout (AudioTranslate.exe, app_cleanup.py, runtime/python, app/{worker,ui,licensing,security-core}) built from
this repository, with the runtime python pointing at the development packages. Data and licence state are in a temporary folder, so the owner's
own data is never touched. The window is read through WebView2's DevTools port. Needs `npm run build` (the UI in ./out) and
`python packaging/build_shell.py` (desktop/bin/AudioTranslate.exe).

    .venv\\Scripts\\python.exe -m unittest packaging.test_shell
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / 'desktop' / 'bin' / 'AudioTranslate.exe'
WINDOWS = os.name == 'nt'
NEEDS = WINDOWS and (ROOT / 'out' / 'index.html').is_file() and (ROOT / 'security-core' / 'bin' / 'audio-security-core.exe').is_file() and SHELL.is_file()


def free_port():
    with socket.socket() as probe: probe.bind(('127.0.0.1', 0)); return probe.getsockname()[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


@unittest.skipUnless(NEEDS, 'needs Windows, `npm run build`, the security core and the built shell')
class ShellOnStandIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='shell-test-'); cls.base = Path(cls.temp.name)
        cls.install = cls.base / 'install'; app = cls.install / 'app'
        shutil.copytree(ROOT / 'worker', app / 'worker', ignore=shutil.ignore_patterns('tests', 'dev', 'docs', '__pycache__', '*.pyc', '*.egg-info', 'tmp*'))
        shutil.copytree(ROOT / 'out', app / 'ui', ignore=shutil.ignore_patterns('voice-previews'))
        shutil.copytree(ROOT / 'public', app / 'public')
        (app / 'licensing').mkdir(); shutil.copy2(ROOT / 'licensing' / 'public-config.json', app / 'licensing' / 'public-config.json')
        (app / 'security-core' / 'bin').mkdir(parents=True); shutil.copy2(ROOT / 'security-core' / 'bin' / 'audio-security-core.exe', app / 'security-core' / 'bin')
        for name in ('app_cleanup.py', 'paths.py'): shutil.copy2(ROOT / 'packaging' / name, cls.install / name)
        shutil.copy2(SHELL, cls.install / 'AudioTranslate.exe')
        runtime = cls.install / 'runtime' / 'python'; runtime.mkdir(parents=True)
        host = Path(sys.base_prefix)
        for pattern in ('python*.exe', 'python*.dll', 'vcruntime*.dll'):
            for found in host.glob(pattern): shutil.copy2(found, runtime / found.name)
        paths = [str(host / 'Lib'), str(host / 'DLLs'), str(ROOT / '.venv' / 'Lib' / 'site-packages'), str(app / 'worker')]
        (runtime / 'python312._pth').write_text('\n'.join(paths) + '\nimport site\n')
        cls.product = json.loads((app / 'licensing' / 'public-config.json').read_text(encoding='utf-8'))['product_id']
        (cls.base / 'localappdata').mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.stop_everything(); time.sleep(1); cls.temp.cleanup()

    @classmethod
    def stop_everything(cls):
        subprocess.run([str(cls.install / 'runtime' / 'python' / 'python.exe'), str(cls.install / 'app_cleanup.py')], capture_output=True, timeout=60,
                       env={**os.environ, 'PYTHONNOUSERSITE': '1'}, creationflags=subprocess.CREATE_NO_WINDOW)

    def setUp(self):
        self.stop_everything(); time.sleep(1)
        self.port, self.debug = free_port(), free_port()
        self.env = {**os.environ, 'LOCALAPPDATA': str(self.base / 'localappdata'), 'AUDIO_DATA_DIR': str(self.base / 'data'),
                    'AUDIO_LICENSE_STATE_ROOT': str(self.base / 'license'), 'AUDIO_API_PORT': str(self.port), 'AUDIO_LAUNCHER_NO_DIALOG': '1',
                    'WEBVIEW2_USER_DATA_FOLDER': str(self.base / 'webview'), 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': f'--remote-debugging-port={self.debug}'}
        shutil.rmtree(self.base / 'data', ignore_errors=True)
        self.shells = []

    def tearDown(self):
        for process in self.shells:
            if process.poll() is None: process.kill()
        self.stop_everything()

    def start_shell(self):
        process = subprocess.Popen([str(self.install / 'AudioTranslate.exe')], env=self.env, cwd=self.install)
        self.shells.append(process); return process

    def app_processes(self, name=None):
        import psutil
        prefix = str(self.install.resolve()).lower() + os.sep
        found = [p for p in psutil.process_iter(['exe', 'name']) if (p.info.get('exe') or '').lower().startswith(prefix)]
        return [p for p in found if name is None or p.info['name'].lower() == name]

    def shell_family(self, shell):
        """The shell and the API it started (its python child); helpers that come and go are not part of it."""
        import psutil
        found = {shell.pid}
        for p in self.app_processes('python.exe'):
            try:
                if p.ppid() == shell.pid: found.add(p.pid)
            except psutil.Error: pass
        return found

    def wait_for(self, condition, seconds=90, what='the condition'):
        end = time.time() + seconds
        while time.time() < end:
            value = condition()
            if value: return value
            time.sleep(0.4)
        self.fail(f'timed out waiting for {what}')

    def session(self):
        def read():
            try: return json.loads((self.base / 'data' / 'local-api.json').read_text(encoding='utf-8'))
            except (OSError, ValueError): return None
        return self.wait_for(read, 30, 'local-api.json')

    def get(self, path, headers=None, method='GET', data=None):
        opener = build_opener(NoRedirect)
        try: response = opener.open(Request(f'http://127.0.0.1:{self.port}{path}', headers=headers or {}, method=method, data=data), timeout=30)
        except HTTPError as error: response = error
        with response: return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()

    def api_ready(self):
        try: return self.get('/api/license', {'X-Audio-Api-Token': self.session()['token']})[0] == 200
        except (URLError, OSError): return False

    def page_url(self):
        """The address the shell's window is showing, read through the WebView2 DevTools port."""
        try:
            with urlopen(f'http://127.0.0.1:{self.debug}/json', timeout=3) as response:
                pages = [t for t in json.load(response) if t.get('type') == 'page']
            return pages[0]['url'] if pages else None
        except (URLError, OSError, ValueError): return None

    def test_start_shows_the_page_and_quit_ends_everything(self):
        shell = self.start_shell()
        self.wait_for(self.api_ready, 90, 'the API')
        token = self.session()['token']
        # The window navigated to the API and the launch token was swapped for the session cookie (the address no longer carries it).
        self.wait_for(lambda: self.page_url() == f'http://127.0.0.1:{self.port}/', 60, 'the window to show the app')
        self.assertEqual(self.app_processes('python.exe') != [], True)
        self.assertEqual({p.info['name'].lower() for p in self.app_processes()}, {'python.exe', 'audiotranslate.exe'})   # no node.exe
        # Quit: the API answers, then exits with the quit code; the shell follows and takes every process of the installation along.
        status, _, body = self.get('/api/quit', {'X-Audio-Api-Token': token}, 'POST', b'{}')
        self.assertEqual((status, json.loads(body)['stopped']), (200, True))
        self.assertIsNotNone(self.wait_for(lambda: shell.poll() is not None and 1, 30, 'the shell to exit') and shell.poll())
        self.wait_for(lambda: not self.app_processes(), 20, 'no process of the installation')
        with self.assertRaises((URLError, OSError)): urlopen(f'http://127.0.0.1:{self.port}/', timeout=3)

    def test_a_crashed_api_is_started_again_with_the_same_token(self):
        self.start_shell(); self.wait_for(self.api_ready, 90, 'the API')
        before = self.session()
        api = self.app_processes('python.exe')[0]; api.kill()
        self.wait_for(lambda: self.api_ready() and self.app_processes('python.exe') and self.app_processes('python.exe')[0].pid != api.pid, 90, 'the API to come back')
        self.assertEqual(self.session(), before)
        cookie = self.get(f'/?launch={before["token"]}')[1]['set-cookie'].split(';')[0]
        self.assertEqual(self.get('/api/license', {'Cookie': cookie})[0], 200)                  # the open page keeps working

    def test_a_second_start_only_brings_the_window_forward(self):
        first = self.start_shell(); self.wait_for(self.api_ready, 90, 'the API')
        self.wait_for(lambda: self.page_url() == f'http://127.0.0.1:{self.port}/', 60, 'the window to show the app')
        # The shell and the API it started. Short-lived helpers (the start-up cleanup, a worker the page's first calls start) come and go.
        pids = self.shell_family(first)
        second = self.start_shell()
        self.wait_for(lambda: second.poll() is not None, 30, 'the second start to hand over')
        self.assertIsNone(first.poll())
        self.assertEqual(self.shell_family(first), pids)

    def test_killing_the_shell_ends_the_api_too(self):
        shell = self.start_shell(); self.wait_for(self.api_ready, 90, 'the API')
        shell.kill()
        self.wait_for(lambda: not self.app_processes('python.exe'), 20, 'the API to end with the shell')

    def test_a_port_held_by_another_program_is_not_taken(self):
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', self.port)); holder.listen(1)
            shell = self.start_shell()
            self.wait_for(lambda: shell.poll() is not None, 60, 'the shell to give up')
        self.assertNotEqual(shell.returncode, 0)
        self.assertEqual(self.app_processes('python.exe'), [])
        self.assertIn('PORT_IN_USE', (self.base / 'localappdata' / 'AudioTranslate' / 'launcher-error.log').read_text(encoding='utf-8'))

    def test_without_the_security_core_nothing_starts(self):
        core = self.install / 'app' / 'security-core' / 'bin' / 'audio-security-core.exe'; hidden = core.with_suffix('.hidden')
        core.rename(hidden)
        try:
            shell = self.start_shell(); self.wait_for(lambda: shell.poll() is not None, 60, 'the shell to give up')
            self.assertNotEqual(shell.returncode, 0); self.assertEqual(self.app_processes('python.exe'), [])
            self.assertIn('NATIVE_SECURITY_CORE_MISSING', (self.base / 'localappdata' / 'AudioTranslate' / 'launcher-error.log').read_text(encoding='utf-8'))
        finally: hidden.rename(core)


if __name__ == '__main__':
    unittest.main()
