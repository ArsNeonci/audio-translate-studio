"""The local API serving the built UI and guarding it (audio_translate/api/app.py, static.py, web.py), over real HTTP."""
from http.client import HTTPConnection
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

import uvicorn

from audio_translate.api import app as api_app, static, web

TOKEN = 'k' * 43
SESSION = web.session_value(TOKEN)


def make_ui(root):
    files = {'index.html': '<h1>home</h1>', 'history.html': '<h1>history</h1>', 'history/view.html': '<h1>view</h1>', '404.html': '<h1>missing</h1>',
             'history/__next.history/__PAGE__.txt': 'segment', 'history/view/__next.history/view/__PAGE__.txt': 'segment-view', 'history/__next._tree.txt': 'tree',
             '_next/static/chunks/a.js': 'console.log(1)', '_next/static/css/a.css': 'body{}', 'arsneonci-logo.png': 'png', 'favicon.ico': 'ico'}
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True); (root / name).write_text(text, encoding='utf-8')
    (root.parent / 'secret.txt').write_text('private', encoding='utf-8')


class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.ui = Path(cls.temp.name) / 'ui'; cls.ui.mkdir(); make_ui(cls.ui)
        with socket.socket() as probe: probe.bind(('127.0.0.1', 0)); cls.port = probe.getsockname()[1]
        cls.server = uvicorn.Server(uvicorn.Config(api_app.create_app(TOKEN, cls.ui), host='127.0.0.1', port=cls.port, log_level='warning'))
        threading.Thread(target=cls.server.run, daemon=True).start()
        while not cls.server.started: time.sleep(0.02)

    @classmethod
    def tearDownClass(cls): cls.server.should_exit = True; cls.temp.cleanup()

    def get(self, path, headers=None, method='GET', host=None, body=None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=30)
        sent = {'Host': host or f'127.0.0.1:{self.port}', **(headers or {})}
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse(); content = response.read(); connection.close()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, content

    COOKIE = {'Cookie': f'audio_session={SESSION}'}


class StaticTests(Live):
    def test_pages_need_the_session_and_assets_do_not(self):
        status, headers, body = self.get('/')
        self.assertEqual(status, 403); self.assertIn('shortcut', body.decode()); self.assertEqual(headers['cache-control'], 'no-store')
        for path in ('/history', '/history/view', '/history.html'): self.assertEqual(self.get(path)[0], 403, path)
        self.assertEqual(self.get('/_next/static/chunks/a.js')[0], 200)
        self.assertEqual(self.get('/favicon.ico')[0], 200)

    def test_pages_map_to_the_export_layout(self):
        for path, text in (('/', 'home'), ('/history', 'history'), ('/history/view?id=x', 'view'), ('/history.html', 'history')):
            status, headers, body = self.get(path, self.COOKIE)
            self.assertEqual((status, text in body.decode(), headers['cache-control']), (200, True, 'no-cache'), path)
        status, headers, body = self.get('/nothing-here', self.COOKIE)
        self.assertEqual((status, 'missing' in body.decode()), (404, True))   # the export's own 404 page

    def test_the_clients_page_data_requests_find_the_files_the_export_wrote(self):
        for path, text in (('/history/__next.history.__PAGE__.txt', 'segment'), ('/history/view/__next.history.view.__PAGE__.txt', 'segment-view'),
                           ('/history/__next._tree.txt', 'tree')):
            status, headers, body = self.get(path + '?_rsc=abc', self.COOKIE)
            self.assertEqual((status, body.decode(), headers['content-type'].split(';')[0]), (200, text, 'text/plain'), path)
        self.assertEqual(self.get('/history/__next.nothing.__PAGE__.txt')[0], 404)

    def test_assets_are_typed_and_cached_for_a_year_only_when_hashed(self):
        status, headers, _ = self.get('/_next/static/chunks/a.js')
        self.assertEqual((headers['content-type'].split(';')[0], headers['cache-control']), ('text/javascript', 'public, max-age=31536000, immutable'))
        self.assertEqual(self.get('/_next/static/css/a.css')[1]['content-type'].split(';')[0], 'text/css')
        self.assertEqual(self.get('/arsneonci-logo.png')[1]['cache-control'], 'no-cache')

    def test_every_page_carries_the_security_headers(self):
        headers = self.get('/', self.COOKIE)[1]
        self.assertEqual((headers['x-content-type-options'], headers['x-frame-options'], headers['referrer-policy']), ('nosniff', 'DENY', 'no-referrer'))

    def test_nothing_outside_the_ui_folder_is_served(self):
        for path in ('/../secret.txt', '/%2e%2e/secret.txt', '/..%2fsecret.txt', '/_next/../../secret.txt', '/%5c..%5csecret.txt', '/C:/Windows/win.ini', '/.%2e/secret.txt'):
            status, _, body = self.get(path, self.COOKIE)
            self.assertNotIn(b'private', body, path)
            self.assertIn(status, (200, 400, 403, 404), path)
        self.assertIsNone(static.locate(self.ui, '/../secret.txt'))
        self.assertIsNone(static.locate(self.ui, '/a/../../secret.txt'))
        self.assertIsNone(static.locate(self.ui, '/..\\secret.txt'))
        self.assertIsNone(static.locate(self.ui, '/C:/x'))
        (self.ui / 'dir').mkdir(exist_ok=True)
        self.assertIsNone(static.locate(self.ui, '/dir'))      # a folder is not a page, no listing

    def test_the_static_files_accept_only_get(self):
        status, _, body = self.get('/history', self.COOKIE, method='POST', body=b'x')
        self.assertEqual(status, 405)


class LaunchAndGuardTests(Live):
    def test_the_launch_link_becomes_a_cookie_and_leaves_the_address(self):
        status, headers, _ = self.get(f'/history?launch={TOKEN}&id=7')
        self.assertEqual((status, headers['location']), (303, '/history?id=7'))   # other parameters stay
        cookie = headers['set-cookie']
        self.assertIn(f'audio_session={SESSION}', cookie)
        for flag in ('HttpOnly', 'SameSite=strict', 'Path=/'): self.assertIn(flag, cookie)
        self.assertNotIn(TOKEN, cookie)                                           # the cookie is derived, not the token itself
        self.assertEqual(self.get('/', {'Cookie': f'audio_session={SESSION}'})[0], 200)

    def test_a_wrong_launch_token_gets_nothing(self):
        status, headers, _ = self.get('/?launch=' + 'x' * 43)
        self.assertEqual(status, 403); self.assertNotIn('set-cookie', headers)

    def test_api_needs_the_cookie_or_the_header(self):
        for headers in ({}, {'X-Audio-Api-Token': 'x' * 43}, {'Cookie': 'audio_session=' + 'a' * 64}):
            status, _, body = self.get('/api/rules', headers)
            self.assertEqual((status, body), (403, b'{"error":"API token required"}'), headers)
        self.assertEqual(self.get('/api/quit', self.COOKIE)[0], 200)
        self.assertEqual(self.get('/api/quit', {'X-Audio-Api-Token': TOKEN})[0], 200)

    def test_a_host_that_is_not_loopback_is_refused_everywhere(self):
        for path in ('/', '/api/quit', '/_next/static/chunks/a.js'):
            status, _, body = self.get(path, {**self.COOKIE, 'X-Audio-Api-Token': TOKEN}, host='evil.example')
            self.assertEqual((status, body), (403, b'{"error":"Host rejected"}'), path)
        for host in ('localhost:1234', '[::1]:1234', f'127.0.0.1:{self.port}'): self.assertEqual(self.get('/api/quit', self.COOKIE, host=host)[0], 200, host)

    def test_changes_from_another_page_are_refused_even_with_the_cookie(self):
        body = b'{"source": "a", "replacement": "b"}'
        json = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        def post(extra): return self.get('/api/rules', {**self.COOKIE, **json, **extra}, method='POST', body=body)[:3:2]
        refused = (403, b'{"error":"Origin rejected"}')
        self.assertEqual(post({'Origin': 'https://evil.example'}), refused)
        self.assertEqual(post({'Origin': 'http://localhost:9999'}), refused)             # another local program on another port
        self.assertEqual(post({'Sec-Fetch-Site': 'same-site'}), refused)
        self.assertEqual(post({'Sec-Fetch-Site': 'cross-site'}), refused)
        for extra in ({'Origin': f'http://127.0.0.1:{self.port}', 'Sec-Fetch-Site': 'same-origin'}, {}):
            self.assertNotEqual(post(extra)[0], 403, extra)    # the page itself (or a plain client with the cookie) gets through to the route

    def test_unknown_api_paths_are_json_404(self):
        status, _, body = self.get('/api/nothing', self.COOKIE)
        self.assertEqual(status, 404)


class ApiOnly(unittest.TestCase):
    def test_without_a_ui_folder_non_api_paths_are_404(self):
        with socket.socket() as probe: probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api_app.create_app(TOKEN), host='127.0.0.1', port=port, log_level='warning'))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started: time.sleep(0.02)
        try:
            connection = HTTPConnection('127.0.0.1', port, timeout=30); connection.request('GET', '/'); response = connection.getresponse()
            self.assertEqual((response.status, response.read()), (404, b'{"error":"Not found"}')); connection.close()
        finally: server.should_exit = True


if __name__ == '__main__':
    unittest.main()
