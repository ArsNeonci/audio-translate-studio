"""audio_translate/api/model.py: the scenarios of scripts/check-model-download.cjs (which checked the TypeScript module it
replaces). A local HTTP server stands in for the file store; a small file replaces the 4.6 GB model."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from audio_translate.api import license as lease, model

PAYLOAD = os.urandom(3 * 1024 * 1024 + 123)


class Store:
    def __init__(self): self.reset()
    def reset(self, served=PAYLOAD, cut_at=0, status=0, slow=False): self.served, self.cut_at, self.status, self.slow, self.ranges, self.agents = served, cut_at, status, slow, [], []


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = store = Store()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_): pass
            def do_GET(self):
                match = re.match(r'bytes=(\d+)-', self.headers.get('Range', ''))
                start = int(match[1]) if match else 0
                store.ranges.append(start); store.agents.append(self.headers.get('User-Agent', ''))
                if store.status: self.send_response(store.status); self.send_header('Content-Length', '0'); self.end_headers(); return
                body = store.served[start:]
                self.send_response(206 if match else 200); self.send_header('Content-Length', str(len(body))); self.end_headers()
                if store.cut_at and not match:
                    self.wfile.write(body[:store.cut_at]); self.wfile.flush(); self.connection.close(); return
                if store.slow:
                    for at in range(0, len(body), 262144): self.wfile.write(body[at:at + 262144]); self.wfile.flush(); time.sleep(0.1)
                    return
                self.wfile.write(body)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.target = Path(temp.name) / 'models' / 'model.gguf'
        self.credential = {'status': 'ACTIVE', 'token': 'LIC.TOKEN'}
        self.gateway, self.url_calls = (200, {}), 0
        self.store.reset()
        def license_command(payload):
            if payload['action'] == 'credential': return {'http_status': 200 if self.credential['status'] == 'ACTIVE' else 403, **self.credential}
            return {'http_status': 200, 'status': self.credential['status']}
        def gateway_call(method, url, token, body=None, timeout=20):
            self.url_calls += 1
            self.assertEqual((method, url, token, body), ('POST', 'https://api.test/v1/model/url', 'LIC.TOKEN', {'model': 'hy-mt2-7b-q4km'}))
            status, refusal = self.gateway
            return (200, {'url': f'http://127.0.0.1:{self.server.server_port}/model'}) if status == 200 else (status, refusal)
        for p in (patch.dict(os.environ, {'HY_MT_MODEL_PATH': str(self.target)}), patch.dict(model.MODEL, {'size': len(PAYLOAD), 'sha256': hashlib.sha256(PAYLOAD).hexdigest()}),
                  patch.object(model, 'RETRY_PAUSE', 0.005), patch.object(model, 'license_command', license_command), patch.object(lease, 'gateway_call', gateway_call),
                  patch.object(lease, 'gateway_endpoint', lambda: 'https://api.test'), patch.dict(model._holder, {'run': None, 'state': {'phase': 'missing', 'done': 0, 'total': len(PAYLOAD)}})):
            p.start(); self.addCleanup(p.stop)

    def settle(self):
        for _ in range(800):
            time.sleep(0.025)
            state = model.model_state()
            if state['phase'] not in ('downloading', 'verifying') and not model._holder['run']: return state
        self.fail('timeout')

    def clean(self):
        import shutil
        shutil.rmtree(self.target.parent, ignore_errors=True)
        model._holder['state'] = {'phase': 'missing', 'done': 0, 'total': len(PAYLOAD)}

    def test_download_verify_and_ready_after_a_restart(self):
        self.assertEqual(model.model_state()['phase'], 'missing')
        model.start_model_download()
        self.assertEqual(self.settle()['phase'], 'ready')
        self.assertEqual((self.url_calls, self.target.read_bytes() == PAYLOAD, Path(f'{self.target}.part').exists()), (1, True, False))
        # Cloudflare (in front of the gateway's file links) refuses Python's default agent with a 403, which the app would report as an expired link.
        self.assertTrue(self.store.agents and all(a == 'audio-translate-app/1' for a in self.store.agents), self.store.agents)
        model._holder['state'] = {'phase': 'missing', 'done': 0, 'total': len(PAYLOAD)}   # as after a restart
        self.assertEqual(model.model_state()['phase'], 'ready')
        self.assertEqual(model.start_model_download()['phase'], 'ready')
        self.settle(); self.assertEqual(self.url_calls, 1)
        with open(self.target, 'ab') as handle: handle.write(b'x')   # changed on disk: the marker no longer matches
        self.assertEqual(model.model_state()['phase'], 'missing')

    def test_a_dropped_connection_resumes_with_a_range(self):
        self.store.reset(cut_at=1024 * 1024)
        model.start_model_download()
        self.assertEqual(self.settle()['phase'], 'ready')
        self.assertTrue(len(self.store.ranges) >= 2 and self.store.ranges[1] > 0, self.store.ranges)
        self.assertEqual(self.target.read_bytes(), PAYLOAD)

    def test_an_expired_link_is_replaced(self):
        self.store.reset(status=403)
        model.start_model_download()
        time.sleep(0.05); self.store.status = 0
        self.assertEqual(self.settle()['phase'], 'ready')
        self.assertGreaterEqual(self.url_calls, 2)

    def test_wrong_bytes_are_deleted_and_reported(self):
        self.store.reset(served=PAYLOAD[:-1] + b'z')
        model.start_model_download()
        state = self.settle()
        self.assertEqual((state['phase'], state['error']), ('error', 'CHECKSUM_MISMATCH'))
        self.assertFalse(self.target.exists() or Path(f'{self.target}.part').exists())

    def test_gateway_refusals_stop_at_once(self):
        for status, code in ((401, 'EXPIRED'), (429, 'MODEL_LINK_LIMIT'), (503, 'MODEL_DOWNLOAD_DISABLED'), (403, 'LICENSE_REVOKED')):
            self.clean(); self.gateway, self.url_calls = (status, {'error': code}), 0
            model.start_model_download()
            state = self.settle()
            self.assertEqual((state['phase'], state['error'], self.url_calls), ('error', code, 1))
        self.clean(); self.gateway, self.credential, self.url_calls = (200, {}), {'status': 'EXPIRED'}, 0
        model.start_model_download()
        self.assertEqual((self.settle()['error'], self.url_calls), ('LICENSE_REQUIRED', 0))   # no request leaves the computer

    def test_a_file_placed_by_hand_is_hashed_without_any_request(self):
        self.target.parent.mkdir(parents=True); self.target.write_bytes(PAYLOAD)
        self.assertEqual(model.model_state()['phase'], 'missing')
        model.start_model_download()
        self.assertEqual((self.settle()['phase'], self.url_calls), ('ready', 0))

    def test_several_clicks_start_one_download(self):
        answers = [model.start_model_download() for _ in range(3)]
        self.assertEqual([a['phase'] for a in answers], ['downloading'] * 3)
        self.assertEqual(self.settle()['phase'], 'ready')
        self.assertEqual((self.url_calls, len(self.store.ranges)), (1, 1))

    def test_state_reports_the_licence_and_the_speed(self):
        self.credential = {'status': 'UNACTIVATED'}
        self.assertEqual(model.model_state()['license'], 'UNACTIVATED')
        self.credential = {'status': 'ACTIVE', 'token': 'LIC.TOKEN'}
        self.assertEqual(model.model_state()['license'], 'ACTIVE')
        self.store.reset(slow=True)
        model.start_model_download()
        measured = None
        for _ in range(200):
            time.sleep(0.05)
            state = model.model_state()
            if state['phase'] == 'downloading' and state.get('rate') and 'eta' in state: measured = state; break
        self.assertTrue(measured and measured['rate'] > 0 and 0 < measured['done'] <= measured['total'], measured)
        self.assertEqual(self.settle()['phase'], 'ready')


if __name__ == '__main__':
    unittest.main()
