"""updater.exe with the real .NET stub: an app-only package is applied over an installation, the new app must report ready, and anything that goes wrong puts the
old app back. A tiny fake "AudioTranslate.exe" stands in for the app (it writes health.json with the version it finds in installation.json, and exits at
once when app\\poison exists, like a release that cannot start). The registry path is private (AUDIO_UNINSTALL_ROOT); nothing real is touched.
Run: .venv\\Scripts\\python.exe -m unittest discover -s packaging -p "test_update_flow.py"
"""
import hashlib
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
CSC = Path(os.environ.get('WINDIR', '')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
TEST_ROOT = r'Software\AudioTranslateTest\UpdaterUninstall'

FAKE_APP = r'''
using System; using System.IO; using System.Text.RegularExpressions; using System.Threading;
class P { static int Main() {
  string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
  string data = Environment.GetEnvironmentVariable("AUDIO_DATA_DIR");
  string version = Regex.Match(File.ReadAllText(Path.Combine(root, "installation.json")), "\"version\"\\s*:\\s*\"([^\"]+)\"").Groups[1].Value;
  File.WriteAllText(Path.Combine(root, "started-" + version + ".txt"), "ran");
  if (File.Exists(Path.Combine(root, "app", "poison"))) return 7;
  Directory.CreateDirectory(Path.Combine(data, "updates"));
  File.WriteAllText(Path.Combine(data, "updates", "health.json"), "{\"version\":\"" + version + "\"}");
  Thread.Sleep(90000); return 0; } }
'''

FAKE_INSTALLER = r'''
using System; using System.IO; using System.Text.RegularExpressions;
class P { static int Main(string[] args) {
  string root = Environment.GetEnvironmentVariable("AUDIO_FAKE_INSTALL_ROOT");
  File.WriteAllText(Path.Combine(root, "installer-ran.txt"), string.Join(" ", args) + "|" + Environment.GetEnvironmentVariable("AUDIO_INSTALL_DIR"));
  int code = int.Parse(Environment.GetEnvironmentVariable("AUDIO_FAKE_INSTALL_CODE"));
  if (code == 0) {
    string marker = Path.Combine(root, "installation.json");
    File.WriteAllText(marker, Regex.Replace(File.ReadAllText(marker), "\"version\"\\s*:\\s*\"[^\"]+\"", "\"version\":\"" + Environment.GetEnvironmentVariable("AUDIO_FAKE_INSTALL_VERSION") + "\""));
  }
  return code; } }
'''


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def compile_exe(source, output, work):
    file = Path(work) / (Path(output).stem + '.cs'); file.write_text(source, encoding='utf-8')
    subprocess.run([str(CSC), '/nologo', '/target:exe', '/optimize+', '/out:' + str(output), str(file)], check=True, creationflags=subprocess.CREATE_NO_WINDOW)


@unittest.skipUnless(WINDOWS and CSC.is_file(), 'needs Windows and the .NET compiler')
class UpdaterFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import winreg
        cls.winreg = winreg
        cls.work = Path(tempfile.mkdtemp())
        build = load('build_installer_for_updater', ROOT / 'packaging' / 'build_installer.py')
        build.compile_stub('updater.cs', cls.work / 'updater.exe', cls.work, 'audio-translate-test', '9.9.9', 'Test')
        compile_exe(FAKE_APP, cls.work / 'AudioTranslate.exe', cls.work)
        compile_exe(FAKE_INSTALLER, cls.work / 'installer.exe', cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self.work))
        self.root, self.data = self.base / 'Test', self.base / 'data'
        (self.root / 'app').mkdir(parents=True); (self.root / 'runtime' / 'python').mkdir(parents=True); self.data.mkdir()
        (self.root / 'app' / 'marker.txt').write_text('old'); (self.root / 'runtime' / 'python' / 'python.exe').write_text('runtime stays')
        shutil.copy2(self.work / 'AudioTranslate.exe', self.root / 'AudioTranslate.exe'); shutil.copy2(self.work / 'updater.exe', self.root / 'updater.exe')
        (self.root / 'uninstall.exe').write_text('old uninstaller')
        (self.root / 'installation.json').write_text(json.dumps({'product_id': 'audio-translate-test', 'version': '1.0.0', 'installed_at': 'then'}))
        self.env = {**os.environ, 'AUDIO_DATA_DIR': str(self.data), 'AUDIO_UNINSTALL_ROOT': TEST_ROOT,
                    'AUDIO_FAKE_INSTALL_ROOT': str(self.root), 'AUDIO_FAKE_INSTALL_VERSION': '2.0.0', 'AUDIO_FAKE_INSTALL_CODE': '0'}
        with self.winreg.CreateKey(self.winreg.HKEY_CURRENT_USER, TEST_ROOT + r'\AudioTranslate-Test') as key:
            self.winreg.SetValueEx(key, 'DisplayVersion', 0, self.winreg.REG_SZ, '1.0.0')
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for process in list(self.running()): process.kill()
        time.sleep(1)
        try:
            self.winreg.DeleteKey(self.winreg.HKEY_CURRENT_USER, TEST_ROOT + r'\AudioTranslate-Test')
            self.winreg.DeleteKey(self.winreg.HKEY_CURRENT_USER, TEST_ROOT)
            self.winreg.DeleteKey(self.winreg.HKEY_CURRENT_USER, r'Software\AudioTranslateTest')
        except OSError: pass

    def running(self):
        import psutil
        prefix = str(self.base).lower()
        return [p for p in psutil.process_iter(['exe']) if (p.info.get('exe') or '').lower().startswith(prefix)]

    def package(self, files, name='package.zip'):
        path = self.base / name
        with zipfile.ZipFile(path, 'w') as z:
            for entry, content in files.items():
                if isinstance(content, Path): z.write(content, entry)
                else: z.writestr(entry, content)
        return path

    def good_files(self, **extra):
        return {'app/marker.txt': 'new', 'AudioTranslate.exe': self.work / 'AudioTranslate.exe', 'updater.exe': self.work / 'updater.exe', 'uninstall.exe': 'new uninstaller', **extra}

    def apply(self, package, version='2.0.0', sha=None, kind='app'):
        sha = sha or hashlib.sha256(package.read_bytes()).hexdigest()
        plan = self.data / 'updates' / 'apply.json'; plan.parent.mkdir(exist_ok=True)
        plan.write_text(json.dumps({'kind': kind, 'package': str(package), 'sha256': sha, 'version': version, 'from_version': '1.0.0', 'install_root': str(self.root), 'data': str(self.data)}))
        subprocess.run([str(self.root / 'updater.exe'), '/apply', str(plan)], env=self.env, timeout=30)      # starts itself from the temp folder and returns
        result = self.data / 'updates' / 'last-update.json'
        for _ in range(240):
            if result.exists(): break
            time.sleep(0.5)
        self.assertTrue(result.exists(), 'the updater did not finish: ' + (self.data / 'updates' / 'updater.log').read_text(errors='replace') if (self.data / 'updates' / 'updater.log').exists() else 'no log')
        return json.loads(result.read_text())

    def started(self, version, seconds=15):
        for _ in range(int(seconds * 2)):
            if (self.root / f'started-{version}.txt').exists(): return True
            time.sleep(0.5)
        return False

    def failed(self):
        path = self.data / 'updates' / 'failed-versions.json'
        return json.loads(path.read_text()) if path.exists() else []

    def registered(self):
        with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, TEST_ROOT + r'\AudioTranslate-Test') as key: return self.winreg.QueryValueEx(key, 'DisplayVersion')[0]

    def assertOldIntact(self):
        self.assertEqual((self.root / 'app' / 'marker.txt').read_text(), 'old')
        self.assertEqual((self.root / 'uninstall.exe').read_text(), 'old uninstaller')
        self.assertEqual(json.loads((self.root / 'installation.json').read_text())['version'], '1.0.0')
        self.assertEqual((self.root / 'runtime' / 'python' / 'python.exe').read_text(), 'runtime stays')
        self.assertFalse((self.root / 'app' / 'poison').exists()); self.assertFalse((self.root / 'app' / '_root').exists())
        self.assertEqual(self.registered(), '1.0.0')

    def test_a_good_package_replaces_the_app_and_the_new_app_must_report_ready(self):
        result = self.apply(self.package(self.good_files()))
        self.assertEqual((result['ok'], result['version'], result['from']), (True, '2.0.0', '1.0.0'))
        self.assertEqual((self.root / 'app' / 'marker.txt').read_text(), 'new')
        self.assertEqual((self.root / 'uninstall.exe').read_text(), 'new uninstaller')                         # root files are replaced too
        self.assertEqual((self.root / 'runtime' / 'python' / 'python.exe').read_text(), 'runtime stays')      # the runtime is never touched
        info = json.loads((self.root / 'installation.json').read_text())
        self.assertEqual((info['version'], info['product_id'], info['updated_from']), ('2.0.0', 'audio-translate-test', '1.0.0'))
        self.assertEqual(self.registered(), '2.0.0')
        self.assertTrue(self.started('2.0.0'))                                                                  # the new app was started
        self.assertEqual((self.root / 'app.old' / 'marker.txt').read_text(), 'old')                            # and the old one is kept for a manual restore
        self.assertEqual(self.failed(), []); self.assertFalse((self.data / 'updates' / 'apply.json').exists())

    def test_a_package_that_does_not_match_its_hash_changes_nothing_and_the_old_app_runs_again(self):
        result = self.apply(self.package(self.good_files()), sha='0' * 64)
        self.assertEqual(result['ok'], False); self.assertEqual(self.failed(), ['2.0.0'])
        self.assertOldIntact(); self.assertTrue(self.started('1.0.0')); self.assertFalse((self.root / 'app.old').exists())

    def test_a_release_that_cannot_start_is_rolled_back_to_the_old_one(self):
        result = self.apply(self.package(self.good_files(**{'app/poison': 'x'})))
        self.assertEqual((result['ok'], result['version']), (False, '2.0.0'))
        self.assertIn('did not start', result['error'])
        self.assertEqual(self.failed(), ['2.0.0'])
        self.assertOldIntact()
        self.assertTrue(self.started('2.0.0'))                                                                  # it was tried
        self.assertTrue(self.started('1.0.0'))                                                                  # and the old app was started again
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.endswith('.old')), [])

    def test_a_package_that_tries_to_touch_the_runtime_or_leave_the_folder_is_refused_and_rolled_back(self):
        for name, files in (('runtime', {'runtime/python/python.exe': 'evil'}), ('providers', {'providers/x.txt': 'evil'}), ('traversal', {'../escape.txt': 'evil'})):
            shutil.rmtree(self.data / 'updates', ignore_errors=True)
            for process in self.running(): process.kill()
            time.sleep(1)
            result = self.apply(self.package(self.good_files(**files), name=name + '.zip'))
            self.assertEqual(result['ok'], False, name)
            self.assertOldIntact(); self.assertFalse((self.base / 'escape.txt').exists(), name)
            self.assertEqual((self.root / 'runtime' / 'python' / 'python.exe').read_text(), 'runtime stays', name)

    def test_the_full_installer_is_run_silently_and_a_failed_one_leaves_the_old_app_running(self):
        installer = self.work / 'installer.exe'
        copy = self.base / 'AudioTranslate-Test-2.0.0.exe'; shutil.copy2(installer, copy)
        self.env['AUDIO_FAKE_INSTALL_CODE'] = '1'
        result = self.apply(copy, kind='installer')
        self.assertEqual(result['ok'], False); self.assertEqual((self.root / 'installer-ran.txt').read_text().strip(), '/Q|' + str(self.root))   # told which folder to replace
        self.assertEqual(self.failed(), ['2.0.0']); self.assertEqual(json.loads((self.root / 'installation.json').read_text())['version'], '1.0.0')
        self.assertTrue(self.started('1.0.0'))
        # A good run: the installer changes the version, the app is started and reports ready.
        for process in self.running(): process.kill()
        time.sleep(1); shutil.rmtree(self.data / 'updates', ignore_errors=True)
        copy2 = self.base / 'second.exe'; shutil.copy2(installer, copy2)
        self.env['AUDIO_FAKE_INSTALL_CODE'] = '0'
        result = self.apply(copy2, kind='installer')
        self.assertEqual((result['ok'], result['version']), (True, '2.0.0'))
        self.assertTrue(self.started('2.0.0'))
        self.assertEqual(self.registered(), '2.0.0')                                                            # the Installed-apps version follows the installer's work
        # A refused downgrade is a failure to report, not a silent success.
        self.assertFalse(copy2.exists())                                                                        # the installer file is removed after use


if __name__ == '__main__':
    unittest.main()
