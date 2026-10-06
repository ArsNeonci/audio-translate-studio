"""Genius mode end to end against the real gateway code (in-process, fake Gemini, synthetic license)."""
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

from audio_translate.core.control import Cancelled  # noqa: E402
from audio_translate.core.storage import atomic_json, read_json  # noqa: E402
from audio_translate.translation import genius  # noqa: E402

ROWS = ['张倩倩回到了家里，她很累。', '李强问她今天去哪里了。', '她说她去医院看了她妈妈。', '李强不相信，他觉得她在撒谎。',
        '第二天，张倩倩发现手镯不见了。', '她马上想到了李强的妹妹。', '妹妹被当场抓住了。']


def b64(raw): return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


@unittest.skipUnless(GATEWAY.is_dir(), 'billing-gateway source not present')
class GeniusTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from gateway import Gateway
        from licensing import canonical
        from store import Store
        self.addCleanup(patch.stopall)
        patch('audio_translate.core.license_gate.assert_allowed', return_value=True).start()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.job = base/'job'; (self.job/'working').mkdir(parents=True)
        atomic_json(self.job/'job.json', {'id': 'genius-test', 'name': 'Genius test', 'status': 'TRANSLATING', 'translation_mode': 'genius',
                                          'selected_address_profile': None, 'steps': {}})
        (self.job/'transcript.zh.jsonl').write_text(''.join(json.dumps({'start_ms': i*1000, 'end_ms': i*1000+900, 'text': t}, ensure_ascii=False)+'\n'
                                                            for i, t in enumerate(ROWS)), encoding='utf-8')
        # Synthetic license chain for customer cust-1 on the Plus edition.
        root, signer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        sign = lambda key, domain, value: b64(key.sign(domain.encode()+b'\0'+canonical(value)))
        cert = {'product_id': 'audio-translate-plus', 'key_version': 1, 'public_key': b64(signer.public_key().public_bytes_raw())}
        now = datetime.now(timezone.utc)
        payload = {'license_id': 'l', 'entitlement_id': 'e', 'customer_id': 'cust-1', 'product_id': 'audio-translate-plus', 'machine_id': 'a'*64,
                   'sequence': 1, 'activated_at': (now-timedelta(days=1)).isoformat(), 'issued_at': now.isoformat(),
                   'expires_at': (now+timedelta(days=30)).isoformat(), 'key_version': 1}
        self.token = b64(canonical({'scheme': 'ed25519-v1', 'certificate': {'payload': cert, 'signature': sign(root, 'product-signing-key-v1', cert)},
                                    'payload': payload, 'signature': sign(signer, 'machine-license-v1', payload)}))
        self.store = Store(base/'gateway.sqlite3')
        self.store.set_products({'audio-translate-plus': b64(root.public_key().public_bytes_raw())})
        self.store.update_settings({'default_price_per_1000': 20})
        self.store.set_customer('cust-1', 'Khách', 1_000_000, None)
        self.calls, self.chinese = [], set()
        self.gateway = Gateway(self.store, '', 'a'*40, call=self.gemini)
        patch.object(genius, 'settings', return_value={'endpoint': 'https://genius.test', 'chunk_rows': 3, 'context_rows': 2, 'max_characters': 30,
                                                      'request_timeout_seconds': 5, 'max_wait_seconds': 0}).start()

    def gemini(self, system, content, settings):
        self.calls.append(content)
        rows = [{'id': r['id'], 'vi': f'Dòng {r["id"]} đã được dịch sang tiếng Việt.' + (' 她' if r['id'] in self.chinese else '')} for r in content['rows']]
        return {'rows': rows, 'characters': [{'zh': '张倩倩', 'vi': 'Trương Thiến Thiến', 'gender': 'female', 'note': 'nữ chính'}]}, {'input': 100, 'output': 50}

    def send(self, endpoint, path, body, token, timeout):
        status, value = self.gateway.handle('POST', path, {'Authorization': f'License {token}'}, json.dumps(body, ensure_ascii=False).encode())
        if status != 200: raise genius.GatewayError(status, value['error'])
        return value

    def run_genius(self):
        return genius.translate(self.job, send=self.send, token=self.token, sleep=lambda _: None)

    def output(self):
        return [json.loads(line) for line in (self.job/'transcript.vi.jsonl').read_text(encoding='utf-8').splitlines()]

    def account(self):
        return self.store.account('cust-1')

    def test_translates_in_chunks_bills_once_and_closes_the_job(self):
        self.run_genius()
        out = self.output()
        self.assertEqual([r['text_zh'] for r in out], ROWS)
        self.assertTrue(all(r['text_vi'].startswith('Dòng') for r in out))
        self.assertEqual(len(self.calls), 3)  # 7 rows / 3 per chunk
        self.assertEqual([r['id'] for r in self.calls[1]['context']], [2, 3])
        self.assertIn('vi', self.calls[1]['context'][0])
        self.assertIn('张倩倩', [c['zh'] for c in self.calls[1]['characters']])
        state = read_json(self.job/'working'/'genius-state.json')
        progress = read_json(self.job/'working'/'genius-progress.json')
        self.assertEqual(progress['billed_chars'], self.account()['billed_chars'])
        self.assertEqual(self.store.jobs()[0]['status'], 'COMPLETED')
        self.assertEqual(self.store.jobs()[0]['job_id'], state['billing_job_id'])
        self.run_genius()  # Completed stage: nothing is sent again.
        self.assertEqual(len(self.calls), 3)

    def test_credit_limit_pauses_and_resume_never_rebills(self):
        self.store.set_customer('cust-1', 'Khách', 3, None)  # Enough for the first chunk only.
        with self.assertRaises(Cancelled): self.run_genius()
        self.assertEqual(read_json(self.job/'job.json')['pause_reason'], 'CREDIT_LIMIT')
        self.assertEqual(read_json(self.job/'working'/'cancel.signal')['mode'], 'pause')
        first = self.account()['billed_chars']; self.assertGreater(first, 0)
        sent = len(self.calls)
        (self.job/'working'/'cancel.signal').unlink()  # What Continue does.
        self.store.set_customer('cust-1', 'Khách', 1_000_000, None)
        self.run_genius()
        self.assertEqual(len(self.calls), sent + 2)
        out = self.output()
        expected = sum(sum(1 for c in r['text_vi'] if not c.isspace()) for r in out)
        self.assertEqual(self.account()['billed_chars'], expected)

    def test_rows_the_gateway_cannot_fix_are_flagged_and_readable(self):
        self.chinese = {5}
        self.run_genius()
        row = self.output()[4]
        self.assertNotIn('她', row['text_vi']); self.assertNotIn('genius_flagged', row)
        self.assertEqual(read_json(self.job/'working'/'genius-progress.json')['flagged_rows'], [5])

    def test_closed_gateway_job_continues_as_a_new_job(self):
        self.store.set_customer('cust-1', 'Khách', 3, None)
        with self.assertRaises(Cancelled): self.run_genius()
        old = read_json(self.job/'working'/'genius-state.json')['billing_job_id']
        self.store.sweep(current=datetime.now(timezone.utc)+timedelta(hours=25))  # Idle > 24 h -> ABANDONED.
        (self.job/'working'/'cancel.signal').unlink()
        self.store.set_customer('cust-1', 'Khách', 1_000_000, None)
        self.run_genius()
        new = read_json(self.job/'working'/'genius-state.json')['billing_job_id']
        self.assertNotEqual(old, new)
        statuses = {j['job_id']: j['status'] for j in self.store.jobs()}
        self.assertEqual((statuses[old], statuses[new]), ('ABANDONED', 'COMPLETED'))

    def test_rejected_license_pauses(self):
        with self.assertRaises(Cancelled): genius.translate(self.job, send=self.send, token='bad', sleep=lambda _: None)
        self.assertEqual(read_json(self.job/'job.json')['pause_reason'], 'LICENSE_REJECTED')

    def test_unreachable_gateway_pauses_after_waiting(self):
        def down(*_): raise genius.GatewayError(0, 'UNREACHABLE')
        with self.assertRaises(Cancelled): genius.translate(self.job, send=down, token=self.token, sleep=lambda _: None)
        self.assertEqual(read_json(self.job/'job.json')['pause_reason'], 'GATEWAY_UNAVAILABLE')


class OrchestratorPauseTests(unittest.TestCase):
    """A credit-limit stop inside the Translation process becomes a resumable PAUSED workflow."""
    def test_credit_limit_pauses_workflow_and_continue_requeues(self):
        import uuid
        from unittest.mock import Mock
        from audio_translate.core.errors import STEPS, initial_steps
        from audio_translate.workflow import manage, results
        from audio_translate.workflow.orchestrator import run
        self.addCleanup(patch.stopall)
        patch('audio_translate.core.license_gate.assert_allowed', return_value=True).start()
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        data = Path(temp.name)/'data'
        for module in (results, manage): patch.object(module, 'DATA', data).start()
        patch.object(results, 'RESULTS', data/'results').start()
        job_id = str(uuid.uuid4()); job = data/'tmp'/job_id; (job/'working').mkdir(parents=True)
        steps = initial_steps({})
        for step in STEPS[:2]: steps[step]['state'] = 'COMPLETED'
        atomic_json(job/'job.json', {'id': job_id, 'status': 'QUEUED', 'name': 'x', 'url': '', 'created_at': '2026-10-06T00:00:00Z',
                                     'translation_mode': 'genius', 'selected_address_profile': None, 'steps': steps})
        (job/'transcript.zh.jsonl').write_text(json.dumps({'start_ms': 0, 'end_ms': 1, 'text': '你好世界'}, ensure_ascii=False)+'\n', encoding='utf-8')
        (job/'transcript.zh.md').write_text('你好世界', encoding='utf-8')
        patch.object(genius, 'settings', return_value={'endpoint': 'https://genius.test', 'chunk_rows': 3, 'context_rows': 2, 'max_characters': 30,
                                                      'request_timeout_seconds': 5, 'max_wait_seconds': 0}).start()
        def limited(*_): raise genius.GatewayError(402, 'CREDIT_LIMIT')
        import subprocess
        real = subprocess.run
        def child(command, **kwargs):
            # The patch is module-global: other subprocesses (e.g. the native edition query) run for real.
            if '--stage' not in command: return real(command, **kwargs)
            try: genius.translate(job, send=limited, token='t', sleep=lambda _: None)
            except Cancelled: return Mock(returncode=2)
            return Mock(returncode=0)
        with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=child):
            self.assertEqual(run(job), 0)
        saved = read_json(job/'job.json')
        self.assertEqual((saved['status'], saved['steps']['TRANSLATION']['state'], saved['pause_reason']), ('PAUSED', 'PAUSED', 'CREDIT_LIMIT'))
        resumed = manage.resume(job_id)
        self.assertEqual((resumed['status'], resumed['pause_reason']), ('QUEUED', None))
        self.assertFalse((job/'working'/'cancel.signal').exists())


class ModeAdmissionTests(unittest.TestCase):
    def test_mode_validation(self):
        from audio_translate.workflow.manage import translation_mode
        self.assertIsNone(translation_mode('normal')); self.assertIsNone(translation_mode(None))
        with self.assertRaisesRegex(ValueError, 'Unknown translation mode'): translation_mode('turbo')
        with patch.object(genius, 'settings', return_value={'endpoint': ''}):
            with self.assertRaisesRegex(ValueError, 'not configured'): translation_mode('genius')
        with patch.object(genius, 'settings', return_value={'endpoint': 'https://genius.test'}):
            self.assertEqual(translation_mode('genius'), 'genius')
            self.assertEqual(translation_mode('genius', 'translation'), 'genius')
            with self.assertRaisesRegex(ValueError, 'Tool 2'): translation_mode('genius', 'tts')


if __name__ == '__main__': unittest.main()
