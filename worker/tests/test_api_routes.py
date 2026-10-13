"""The local API over real HTTP (uvicorn on a free port): the token, origin checks (scenarios of scripts/check-origin.cjs) and
a workflow from an uploaded audio file (scenarios of scripts/check-workflow-upload.cjs). The worker and the licence are faked."""
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import requests
import uvicorn

from audio_translate.api import app as api_app, routes_jobs, web

TOKEN = 't' * 43


class FakeRequest:
    """What origin_allowed reads: the Host header, the scheme of the request and the Origin header."""
    def __init__(self, host, origin, scheme='http'):
        from types import SimpleNamespace
        self.headers = {'host': host, **({'origin': origin} if origin is not None else {})}
        self.url = SimpleNamespace(scheme=scheme)


class OriginTests(unittest.TestCase):
    def ask(self, host, origin): return web.origin_allowed(FakeRequest(host, origin))

    def test_the_launcher_page_is_accepted_under_either_loopback_name(self):
        for host, origin in (('localhost:3210', None), ('localhost:3210', 'http://localhost:3210'), ('localhost:3210', 'http://127.0.0.1:3210'),
                             ('127.0.0.1:3210', 'http://localhost:3210'), ('localhost:3210', 'http://[::1]:3210')):
            self.assertTrue(self.ask(host, origin), (host, origin))

    def test_other_sites_ports_schemes_and_lookalikes_are_refused(self):
        for host, origin in (('localhost:3210', 'https://evil.example'), ('localhost:3210', 'http://localhost:9999'), ('localhost:3210', 'http://127.0.0.1:4000'),
                             ('localhost:3210', 'http://localhost.evil.example:3210'), ('localhost:3210', 'https://localhost:3210'), ('localhost:3210', 'null'),
                             ('localhost:3210', 'not a url'), ('app.example:3210', 'http://127.0.0.1:3210')):
            self.assertFalse(self.ask(host, origin), (host, origin))


class LiveApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe: probe.bind(('127.0.0.1', 0)); cls.port = probe.getsockname()[1]
        cls.server = uvicorn.Server(uvicorn.Config(api_app.create_app(TOKEN), host='127.0.0.1', port=cls.port, log_level='warning'))
        threading.Thread(target=cls.server.run, daemon=True).start()
        while not cls.server.started: time.sleep(0.02)

    @classmethod
    def tearDownClass(cls): cls.server.should_exit = True

    def post(self, path, data=None, headers=None, token=TOKEN):
        return requests.post(f'http://127.0.0.1:{self.port}{path}', data=data, headers={**({'X-Audio-Api-Token': token} if token else {}), **(headers or {})}, timeout=60)


class UploadTests(LiveApi):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)
        self.calls, self.reply, self.scheduled = [], {'status': 200, 'job': {'id': 'job-1'}}, 0
        def command(payload):
            self.calls.append({'payload': payload, 'bytes': Path(payload['upload']).read_bytes() if payload.get('upload') else None})
            return dict(self.reply)
        def soon(delay=0.0): self.scheduled += 1
        for p in (patch.object(routes_jobs, 'DATA', self.data), patch.object(routes_jobs, 'command', command), patch.object(routes_jobs, 'license_denial', lambda: None),
                  patch.object(routes_jobs, 'ensure_history', lambda: None), patch.object(routes_jobs.scheduler, 'soon', soon)):
            p.start(); self.addCleanup(p.stop)

    def leftovers(self): return list((self.data / 'uploads').iterdir()) if (self.data / 'uploads').exists() else []

    def test_a_file_becomes_a_workflow_and_the_temporary_copy_goes(self):
        audio = bytes([7]) * (3 * 1024 * 1024 + 17)
        r = self.post('/api/jobs?name=clip.mp3&voice=v1&style=drama&mode=genius&address=drama&auto=1&queue_only=1', audio, {'Content-Type': 'audio/mpeg'})
        self.assertEqual((r.status_code, r.json()), (201, {'job': {'id': 'job-1'}}))
        payload, received = self.calls[-1]['payload'], self.calls[-1]['bytes']
        self.assertEqual({k: payload.get(k) for k in ('action', 'url', 'tool', 'input_name', 'mime', 'voice', 'style', 'mode', 'address', 'auto', 'queue_only')},
                         {'action': 'convert', 'url': '', 'tool': None, 'input_name': 'clip.mp3', 'mime': 'audio/mpeg', 'voice': 'v1', 'style': 'drama',
                          'mode': 'genius', 'address': None, 'auto': True, 'queue_only': True})   # Genius handles forms of address itself
        self.assertEqual(received, audio)
        self.assertEqual((self.leftovers(), self.scheduled), ([], 1))

    def test_defaults(self):
        r = self.post('/api/jobs?name=clip.wav&address=drama', b'x' * 1000, {'Content-Type': ''})
        self.assertEqual(r.status_code, 201, r.text)
        payload = self.calls[-1]['payload']
        self.assertEqual((payload['queue_only'], payload['auto'], payload['address']), (False, False, 'drama'))

    def test_refused_before_the_worker_is_asked(self):
        for query in ('?name=a%2Fb.mp3', '', '?name=clip.mp3&style=nope', '?name=clip.mp3&mode=nope', '?name=clip.mp3&address=nope'):
            self.assertEqual(self.post(f'/api/jobs{query}', b'abc', {'Content-Type': 'audio/mpeg'}).status_code, 400, query)
        # A declared size over 2 GB is refused from the header alone, before any byte is read.
        from http.client import HTTPConnection
        connection = HTTPConnection('127.0.0.1', self.port, timeout=30)
        connection.putrequest('POST', '/api/jobs?name=clip.mp3')
        for key, value in (('X-Audio-Api-Token', TOKEN), ('Content-Type', 'audio/mpeg'), ('Content-Length', str(2 * 1024 ** 3 + 1))): connection.putheader(key, value)
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 413)
        connection.close()
        self.assertEqual((self.calls, self.leftovers()), ([], []))

    def test_the_workers_refusal_passes_through_and_the_file_still_goes(self):
        self.reply = {'status': 409, 'error': 'Unsupported audio type'}
        r = self.post('/api/jobs?name=clip.mp3', b'abc', {'Content-Type': 'audio/mpeg'})
        self.assertEqual((r.status_code, r.json()['error'], self.leftovers(), self.scheduled), (409, 'Unsupported audio type', [], 0))

    def test_a_youtube_link_still_works(self):
        self.reply = {'status': 200, 'job': {'id': 'job-2'}}
        r = self.post('/api/jobs', '{"url": "https://www.youtube.com/watch?v=abcdefghijk"}', {'Content-Type': 'application/json'})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((self.calls[-1]['payload']['url'], 'upload' in self.calls[-1]['payload']), ('https://www.youtube.com/watch?v=abcdefghijk', False))
        self.assertEqual(self.post('/api/jobs', '{"url": "not a link"}', {'Content-Type': 'application/json'}).status_code, 400)

    def test_without_the_token_nothing_runs(self):
        r = self.post('/api/jobs?name=clip.mp3', b'abc', {'Content-Type': 'audio/mpeg'}, token=None)
        self.assertEqual((r.status_code, r.json(), self.calls, self.leftovers()), (403, {'error': 'API token required'}, [], []))


class YoutubeUrlTests(unittest.TestCase):
    def test_accepted_and_refused_links(self):
        from audio_translate.api.jobs import valid_youtube_url
        for good in ('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'https://youtu.be/dQw4w9WgXcQ', 'https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=5',
                     'https://youtube.com/shorts/dQw4w9WgXcQ', 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', 'https://www.youtube.com/live/dQw4w9WgXcQ/'):
            self.assertTrue(valid_youtube_url(good), good)
        for bad in ('http://www.youtube.com/watch?v=dQw4w9WgXcQ', 'https://user@youtube.com/watch?v=dQw4w9WgXcQ', 'https://www.youtube.com:444/watch?v=dQw4w9WgXcQ',
                    'https://evil.com/watch?v=dQw4w9WgXcQ', 'https://www.youtube.com/watch?v=short', 'https://youtu.be/dQw4w9WgXc', 'not a link', ''):
            self.assertFalse(valid_youtube_url(bad), bad)


if __name__ == '__main__':
    unittest.main()
