"""Basic voice generation through the real gateway code (in-process, fake synthesizer, synthetic license)."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

GATEWAY = Path(__file__).resolve().parents[3]/'billing-gateway'
if GATEWAY.is_dir(): sys.path.insert(0, str(GATEWAY))

from audio_translate.core import edition  # noqa: E402
from audio_translate.core.control import Cancelled  # noqa: E402
from audio_translate.core.storage import atomic_json, read_json  # noqa: E402
from audio_translate.translation import genius  # noqa: E402
from audio_translate.workflow.postprocess import audio_info, synthesize  # noqa: E402

ROWS = ['Trương Thiến Thiến về đến nhà, cô rất mệt.', 'Lý Cường hỏi hôm nay cô đi đâu.', 'Cô nói cô đến bệnh viện thăm mẹ.',
        'Lý Cường không tin.', 'Ngày hôm sau, chiếc vòng tay biến mất.', 'Cô lập tức nghĩ đến em gái của Lý Cường.', '']


def b64(raw): return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


@unittest.skipUnless(GATEWAY.is_dir(), 'billing-gateway source not present')
class RemoteTTSTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import tts_engine
        from gateway import Gateway
        from licensing import canonical
        from store import Store
        from test_platform import fake_worker
        self.addCleanup(patch.stopall)
        patch('audio_translate.core.license_gate.assert_allowed', return_value=True).start()
        patch.object(edition, '_cached', 'basic').start()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.job = base/'job'; (self.job/'working').mkdir(parents=True)
        atomic_json(self.job/'job.json', {'id': 'tts-remote', 'name': 'Voice test', 'status': 'TTS_GENERATING', 'selected_voice_id': 'Ngọc Huyền',
                                          'selected_voice_style': 'drama', 'steps': {}})
        (self.job/'transcript.vi.moderated.jsonl').write_text(''.join(json.dumps({'start_ms': i*2000, 'end_ms': i*2000+1500, 'text_vi': t, 'text_vi_moderated': t},
                                                                                  ensure_ascii=False)+'\n' for i, t in enumerate(ROWS)), encoding='utf-8')
        root, signer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        sign = lambda key, domain, value: b64(key.sign(domain.encode()+b'\0'+canonical(value)))
        cert = {'product_id': 'audio-translate-basic', 'key_version': 1, 'public_key': b64(signer.public_key().public_bytes_raw())}
        now = datetime.now(timezone.utc)
        payload = {'license_id': 'l', 'entitlement_id': 'e', 'customer_id': 'cust-1', 'product_id': 'audio-translate-basic', 'machine_id': 'a'*64,
                   'sequence': 1, 'activated_at': (now-timedelta(days=1)).isoformat(), 'issued_at': now.isoformat(),
                   'expires_at': (now+timedelta(days=30)).isoformat(), 'key_version': 1}
        token = b64(canonical({'scheme': 'ed25519-v1', 'certificate': {'payload': cert, 'signature': sign(root, 'product-signing-key-v1', cert)},
                               'payload': payload, 'signature': sign(signer, 'machine-license-v1', payload)}))
        self.store = Store(base/'gateway.sqlite3')
        self.store.set_app('audio-translates', 'Audio Translate', ['translation', 'tts'], {'audio-translate-basic': b64(root.public_key().public_bytes_raw())})
        self.store.update_settings({'default_price_per_1000': 10}, 'audio-translates', 'tts')
        self.store.set_customer('cust-1', 'Khách', 1_000_000)
        self.sent = []
        self.pool = tts_engine.Pool(1, fake_worker())
        self.gateway = Gateway(self.store, '', 'a'*40, pool=self.pool, results=base/'results')
        patch.object(genius, 'settings', return_value={'endpoint': 'https://gateway.test', 'tts_chunk_chars': 90, 'tts_inflight': 2,
                                                      'tts_poll_seconds': 0.02, 'max_wait_seconds': 0, 'request_timeout_seconds': 5}).start()
        patch.object(genius, 'credential', return_value=token).start()
        patch.object(genius, 'post', side_effect=self.send).start()

    def send(self, endpoint, path, body, token, timeout):
        if path == '/v1/tts' and body not in self.sent: self.sent.append(body)
        status, value = self.gateway.handle('POST', path, {'Authorization': f'License {token}'}, json.dumps(body, ensure_ascii=False).encode())
        if status >= 300: raise genius.GatewayError(status, value['error'])
        return value

    def units_sent(self):
        return sorted({u['id'] for body in self.sent for u in body['units']})

    def test_basic_voice_is_generated_remotely_in_chunks_and_billed_by_input(self):
        synthesize(self.job)
        manifest = [json.loads(l) for l in (self.job/'voice'/'voice.manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue((self.job/'voice.vi.wav').exists())
        for item in manifest: audio_info(self.job/'voice'/item['file'])
        self.assertTrue(all('gap_after_ms' in item for item in manifest))  # Drama grouping and pauses kept.
        self.assertGreater(len({json.dumps(b['units']) for b in self.sent}), 1)  # Several chunks of about 90 characters.
        self.assertEqual(self.sent[0]['voice'], 'Ngọc Huyền'); self.assertEqual(self.sent[0]['style']['id'], 'drama')
        texts = [item['text'] for item in manifest if item['text'].strip()]
        account = self.store.account('cust-1', app_id='audio-translates', service='tts')
        self.assertEqual(account['by_service']['audio-translates/tts']['chars'], sum(sum(1 for c in t if not c.isspace()) for t in texts))
        state = read_json(self.job/'working'/'tts-remote-state.json')
        self.assertEqual({j['job_id']: j['status'] for j in self.store.jobs()}[state['billing_job_id']], 'COMPLETED')
        config = read_json(self.job/'working'/'adapters.json')['tts']
        self.assertEqual((config['backend'], config['device']), ('remote', 'cpu'))

    def test_interrupted_run_resumes_without_resending_saved_units(self):
        original = self.send
        def flaky(endpoint, path, body, token, timeout):
            if path == '/v1/tts':
                # Stop once the first chunk is saved locally, as if the credit limit was reached mid-run.
                if any((self.job/'voice').glob('*.wav')) and not (self.job/'working'/'stop').exists():
                    (self.job/'working'/'stop').write_text('1'); raise genius.GatewayError(402, 'CREDIT_LIMIT')
            return original(endpoint, path, body, token, timeout)
        genius.post.side_effect = flaky
        with self.assertRaises(Cancelled): synthesize(self.job)
        self.assertEqual(read_json(self.job/'job.json')['pause_reason'], 'CREDIT_LIMIT')
        saved = {p.stem for p in (self.job/'voice').glob('*.wav')}
        self.assertTrue(saved)
        (self.job/'working'/'cancel.signal').unlink()
        self.sent.clear()
        synthesize(self.job)
        resent = {f'{i:06d}' for i in self.units_sent()}
        self.assertFalse(resent & saved)  # Only units without a valid WAV were sent again.
        self.assertTrue((self.job/'voice.vi.wav').exists())

    def test_credit_limit_and_rejected_license_pause(self):
        self.store.set_customer('cust-1', 'Khách', 0)
        with self.assertRaises(Cancelled): synthesize(self.job)
        self.assertEqual(read_json(self.job/'job.json')['pause_reason'], 'CREDIT_LIMIT')
        (self.job/'working'/'cancel.signal').unlink()
        genius.credential.side_effect = genius.GatewayError(401, 'EXPIRED')
        with self.assertRaises(Cancelled): synthesize(self.job)
        self.assertEqual(read_json(self.job/'job.json')['pause_reason'], 'LICENSE_REJECTED')


if __name__ == '__main__': unittest.main()
