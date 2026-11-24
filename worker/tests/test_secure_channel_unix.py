"""The Linux side of the security channel: framing over a unix socket, and the refusal of a server that does not run as root. Skipped on Windows."""
import json
import os
import socket
import tempfile
import threading
import unittest

from audio_translate.core import secure_channel

LINUX = os.name != 'nt' and hasattr(os, 'fork')


def serve_once(path, answer, ready, drop_to=None):
    """One framed request answered with `answer` (a dict, or raw bytes to send as they are). With drop_to, the server first gives up root."""
    if drop_to is not None: os.setuid(drop_to)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); server.bind(path); server.listen(1); ready()
    connection, _ = server.accept()
    with connection:
        length = int.from_bytes(connection.recv(4), 'big'); request = json.loads(connection.recv(length))
        body = answer if isinstance(answer, bytes) else json.dumps({**answer, 'echo': request.get('action')}).encode()
        connection.sendall(body if isinstance(answer, bytes) else len(body).to_bytes(4, 'big') + body)
    server.close()


@unittest.skipUnless(LINUX, 'unix sockets and fork')
class UnixChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, 'core.sock')
        self.saved = os.environ.get('AUDIO_SECURITY_SOCKET'); self.addCleanup(self.restore)

    def restore(self):
        if self.saved is None: os.environ.pop('AUDIO_SECURITY_SOCKET', None)
        else: os.environ['AUDIO_SECURITY_SOCKET'] = self.saved

    def start(self, answer):
        ready = threading.Event(); thread = threading.Thread(target=serve_once, args=(self.path, answer, ready.set), daemon=True); thread.start(); ready.wait(5)
        return thread

    def test_a_request_is_framed_and_the_answer_comes_back(self):
        os.environ['AUDIO_SECURITY_SOCKET'] = self.path; self.start({'http_status': 200, 'product_id': 'audio-translate-plus'})
        reply = secure_channel.call({'action': 'identity'})
        self.assertEqual((reply['http_status'], reply['echo']), (200, 'identity'))

    def test_a_missing_socket_is_service_unavailable(self):
        os.environ['AUDIO_SECURITY_SOCKET'] = self.path
        with self.assertRaises(secure_channel.ServiceUnavailable): secure_channel.call({'action': 'identity'})
        self.assertFalse(secure_channel.available())

    def test_an_oversize_answer_is_refused(self):
        os.environ['AUDIO_SECURITY_SOCKET'] = self.path; self.start((17 * 1024 * 1024).to_bytes(4, 'big'))
        with self.assertRaises(secure_channel.ServiceUnavailable): secure_channel.call({'action': 'identity'})

    @unittest.skipUnless(hasattr(os, 'geteuid') and os.geteuid() == 0, 'needs root to start a server as another user')
    def test_a_server_that_is_not_root_is_refused_unless_a_development_socket_was_named(self):
        os.chmod(self.temp.name, 0o777)   # the look-alike runs as another user and must be able to create its socket here
        ready_read, ready_write = os.pipe(); pid = os.fork()
        if pid == 0:   # the look-alike: an ordinary user's server on the expected path
            try: serve_once(self.path, {'http_status': 200}, lambda: os.write(ready_write, b'1'), drop_to=65534)
            finally: os._exit(0)
        os.close(ready_write)   # if the child dies before it is ready, the read below ends instead of waiting for ever
        self.assertEqual(os.read(ready_read, 1), b'1', 'the look-alike server did not start')
        os.chmod(self.path, 0o666)
        saved_dir = secure_channel._SOCKET_DIR
        try:
            secure_channel._SOCKET_DIR = self.temp.name
            os.environ.pop('AUDIO_SECURITY_SOCKET', None)
            with self.assertRaises(secure_channel.ServiceUnavailable) as caught: secure_channel._call_unix(b'{"action":"identity"}', 'core', 2000)
            self.assertIn('not run by root', str(caught.exception))
        finally:
            secure_channel._SOCKET_DIR = saved_dir
            os.waitpid(pid, 0)


if __name__ == '__main__':
    unittest.main()
