"""remote_files.py: what would be run on the gateway server (nothing is executed): no-clobber, key options, quoting, parsing."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remote_files  # noqa: E402


class Result:
    def __init__(self, code=0, out='', err=''): self.returncode, self.stdout, self.stderr = code, out, err


class Recorder:
    def __init__(self, replies=None): self.calls, self.replies = [], list(replies or [])
    def __call__(self, command, **kwargs):
        self.calls.append(command)
        return self.replies.pop(0) if self.replies else Result()


def store(run, key=Path('K')):
    return remote_files.SshFiles('ubuntu@203.0.113.5', key, '/var/lib/audio-gateway/files', run)


class RemoteFilesTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(remote_files.shutil, 'which', side_effect=lambda name: name)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_unsafe_names_are_refused_before_anything_runs(self):
        run = Recorder()
        for bad in ('', '/etc/passwd', '../x', 'a/../b', 'a//b', '-rf', 'a/-b'):
            with self.assertRaises(ValueError, msg=bad): store(run).exists(bad)
        self.assertEqual(run.calls, [])

    def test_ssh_options_carry_the_key_and_never_ask_for_a_password(self):
        run = Recorder([Result(0)]); store(run).exists('youtube/manifest.json')
        command = run.calls[0]
        self.assertEqual(command[0], 'ssh'); self.assertIn('BatchMode=yes', command); self.assertIn('K', command)
        self.assertEqual(command[-2], 'ubuntu@203.0.113.5')
        self.assertEqual(command[-1], 'sudo test -e /var/lib/audio-gateway/files/youtube/manifest.json')

    def test_put_leaves_an_existing_file_alone_unless_replacing(self):
        run = Recorder([Result(0)])                                    # exists -> True
        self.assertFalse(store(run).put('local.whl', 'youtube/a.whl'))
        self.assertEqual(len(run.calls), 1)                            # no scp, no install
        run = Recorder([Result(0)])
        self.assertTrue(store(run).put('local.json', 'youtube/manifest.json', replace=True))
        self.assertEqual([c[0] for c in run.calls], ['scp', 'ssh'])

    def test_put_copies_then_installs_owned_by_the_service_and_cleans_up(self):
        run = Recorder([Result(1), Result(0), Result(0)])              # does not exist, scp ok, install ok
        self.assertTrue(store(run).put('C:/x/model.gguf', 'models/m/model.gguf'))
        exists, scp, install = run.calls
        self.assertEqual(scp[0], 'scp'); self.assertIn('C:/x/model.gguf', scp)
        self.assertRegex(scp[-1], r'^ubuntu@203\.0\.113\.5:\.upload-[0-9a-f]{32}$')
        remote = install[-1]
        for part in ('sudo install -d -o audio-gateway -g audio-gateway -m 750 /var/lib/audio-gateway/files/models/m', 'sudo mv ',
                     '/var/lib/audio-gateway/files/models/m/model.gguf.part', 'sudo chmod 640', 'sudo mv -f', 'rm -f .upload-'):
            self.assertIn(part, remote)

    def test_a_failed_copy_or_install_stops_with_the_reason(self):
        with self.assertRaises(SystemExit) as caught: store(Recorder([Result(1), Result(1, err='no space left')])).put('a', 'x/a')
        self.assertIn('no space left', str(caught.exception))
        with self.assertRaises(SystemExit) as caught: store(Recorder([Result(1), Result(0), Result(1, err='sudo: a password is required')])).put('a', 'x/a')
        self.assertIn('password is required', str(caught.exception))

    def test_names_with_spaces_are_quoted(self):
        run = Recorder([Result(0)]); store(run).exists('models/Hy MT/a b.gguf')
        self.assertEqual(run.calls[0][-1], "sudo test -e '/var/lib/audio-gateway/files/models/Hy MT/a b.gguf'")

    def test_cat_returns_bytes_or_none(self):
        self.assertEqual(store(Recorder([Result(0, b'{"serial": 1}')])).cat('youtube/manifest.json'), b'{"serial": 1}')
        self.assertIsNone(store(Recorder([Result(1, b'')])).cat('youtube/manifest.json'))

    def test_sizes_and_sha256_parse_the_servers_answers(self):
        listing = 'a.whl 1200\nb.whl 99\nmanifest.json 400\nbroken line\n'
        self.assertEqual(store(Recorder([Result(0, listing)])).sizes('youtube/'), {'youtube/a.whl': 1200, 'youtube/b.whl': 99, 'youtube/manifest.json': 400})
        digest = 'a' * 64
        out = f'{digest}  /var/lib/audio-gateway/files/models/m/x.gguf\n{"b" * 64} */var/lib/other/y\n'
        self.assertEqual(store(Recorder([Result(0, out)])).sha256(['models/m/x.gguf']), {'models/m/x.gguf': digest})
        self.assertEqual(store(Recorder()).sha256([]), {})

    def test_local_sha256(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'f'; path.write_bytes(b'abc')
            self.assertEqual(remote_files.local_sha256(path), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')


if __name__ == '__main__':
    unittest.main()
