"""Install, update and uninstall with the real .NET stubs, and the launcher's "stop everything" - on Windows only.

Uses its own edition ("Test", version 9.9.9), so a real Basic/Plus installation, its shortcut and the user's data are never touched.
Never passes /DATA to the uninstaller. Run: .venv\\Scripts\\python.exe -m unittest packaging.test_install_flow  (from audio-translates)
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging'))
WINDOWS = os.name == 'nt'
PING = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32' / 'PING.EXE'
KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\AudioTranslate-Test-9.9.9'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def fake_server(folder):
    """A harmless long-running program that sits where node.exe would, to stand in for the app's server."""
    exe = Path(folder) / 'runtime' / 'node' / 'node.exe'
    exe.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(PING, exe)
    return subprocess.Popen([str(exe), '-t', '127.0.0.1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


@unittest.skipUnless(WINDOWS, 'Windows only')
class LauncherQuit(unittest.TestCase):
    def test_only_processes_of_this_installation_are_stopped(self):
        launcher = load('launcher_under_test', ROOT / 'packaging' / 'launcher.py')
        with tempfile.TemporaryDirectory() as work:
            mine, elsewhere = fake_server(Path(work) / 'install'), fake_server(Path(work) / 'other-install')
            try:
                time.sleep(0.5)
                self.assertEqual(launcher.stop_app(Path(work) / 'install'), 1)
                self.assertIsNotNone(mine.wait(10))             # stopped
                self.assertIsNone(elsewhere.poll())             # a different folder is left alone
            finally:
                for process in (mine, elsewhere):
                    if process.poll() is None: process.kill()


@unittest.skipUnless(WINDOWS and (Path(os.environ.get('WINDIR', '')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe').is_file(), 'needs Windows and the .NET compiler')
class InstallFlow(unittest.TestCase):
    def setUp(self):
        import winreg
        self.winreg = winreg
        self.work = Path(tempfile.mkdtemp())
        self.base = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'AudioTranslate'
        self.target = self.base / 'Test-9.9.9'
        self.link = Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Audio Translate Test.lnk'
        self.assertFalse(self.target.exists(), 'a previous test run left an installation behind')
        self.real = sorted(p.name for p in self.base.iterdir()) if self.base.exists() else []
        build = load('build_installer_under_test', ROOT / 'packaging' / 'build_installer.py')
        stub = self.work / 'setup.exe'
        build.compile_stub('installer.cs', stub, self.work, 'audio-translate-test', '9.9.9', 'Test')
        remover = self.work / 'uninstall.exe'
        build.compile_stub('uninstaller.cs', remover, self.work, 'audio-translate-test', '9.9.9', 'Test')
        payload = self.work / 'payload.zip'
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.write(remover, 'uninstall.exe')
            archive.write(ROOT / 'packaging' / 'app-icon.ico', 'app.ico')
            archive.writestr('launcher.py', '# stand-in')
            archive.writestr('runtime/python/pythonw.exe', 'stand-in')
            archive.writestr('app/marker.txt', 'version one')
        self.setup = self.work / 'AudioTranslate-Test-9.9.9.exe'
        with self.setup.open('wb') as output:
            output.write(stub.read_bytes()); output.write(payload.read_bytes()); output.write(b'ATSETUP1' + payload.stat().st_size.to_bytes(8, 'little'))

    def tearDown(self):
        subprocess.run([str(self.target / 'uninstall.exe'), '/Q'], check=False) if (self.target / 'uninstall.exe').exists() else None
        time.sleep(4)
        shutil.rmtree(self.target, ignore_errors=True)
        try: self.link.unlink()
        except OSError: pass
        try: self.winreg.DeleteKey(self.winreg.HKEY_CURRENT_USER, KEY)
        except OSError: pass
        shutil.rmtree(self.work, ignore_errors=True)

    def registered(self):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, KEY) as key:
                return {name: self.winreg.QueryValueEx(key, name)[0] for name in ('DisplayName', 'DisplayVersion', 'Publisher', 'InstallLocation', 'UninstallString', 'QuietUninstallString', 'NoModify')}
        except OSError: return None

    def test_install_update_in_place_and_uninstall(self):
        # 1. First install: files, marker, Start-menu shortcut and a Windows "Installed apps" entry that runs the uninstaller.
        self.assertEqual(subprocess.run([str(self.setup), '/Q']).returncode, 0)
        self.assertEqual((self.target / 'app' / 'marker.txt').read_text(), 'version one')
        self.assertEqual(json.loads((self.target / 'installation.json').read_text())['version'], '9.9.9')
        self.assertTrue(self.link.exists())
        entry = self.registered()
        self.assertEqual((entry['DisplayName'], entry['DisplayVersion'], entry['Publisher'], entry['NoModify']), ('Audio Translate Test 9.9.9', '9.9.9', 'Ars Neonci', 1))
        self.assertEqual(entry['UninstallString'], f'"{self.target / "uninstall.exe"}"')
        self.assertEqual(entry['QuietUninstallString'], f'"{self.target / "uninstall.exe"}" /Q')

        # 2. Running the installer again over the same version updates it: the running server is stopped, leftovers are removed.
        server = fake_server(self.target)
        (self.target / 'app' / 'marker.txt').write_text('edited by hand')
        (self.target / 'stale-file-from-an-older-build.txt').write_text('x')
        time.sleep(0.5)
        try:
            self.assertEqual(subprocess.run([str(self.setup), '/Q']).returncode, 0)
            self.assertIsNotNone(server.wait(10), 'the running app was not stopped')
        finally:
            if server.poll() is None: server.kill()
        self.assertEqual((self.target / 'app' / 'marker.txt').read_text(), 'version one')
        self.assertFalse((self.target / 'stale-file-from-an-older-build.txt').exists())
        self.assertTrue((self.target / 'installation.json').exists())

        # 3. Uninstall (quiet, user data kept): the folder, the shortcut and the registry entry all go; real installations are untouched.
        self.assertEqual(subprocess.run([str(self.target / 'uninstall.exe'), '/Q']).returncode, 0)
        for _ in range(40):
            if not self.target.exists(): break
            time.sleep(0.5)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.link.exists())
        self.assertIsNone(self.registered())
        self.assertEqual(sorted(p.name for p in self.base.iterdir()) if self.base.exists() else [], self.real)

    def test_the_uninstaller_refuses_a_folder_that_is_not_an_installation(self):
        stray = self.work / 'not-an-install'; stray.mkdir()
        shutil.copy2(self.work / 'uninstall.exe', stray / 'uninstall.exe'); (stray / 'precious.txt').write_text('keep')
        self.assertEqual(subprocess.run([str(stray / 'uninstall.exe'), '/Q']).returncode, 1)
        self.assertTrue((stray / 'precious.txt').exists())


if __name__ == '__main__':
    unittest.main()
