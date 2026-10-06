"""Basic and Plus both keep the Chinese transcript; sealed jobs of an earlier Basic build stay readable."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from audio_translate.core import edition, sealing
from audio_translate.core.errors import STEPS, initial_steps
from audio_translate.core.storage import atomic_json, file_digest, read_json
from audio_translate.moderation.rules import ReplacementRules
from audio_translate.workflow import manage, results
from audio_translate.workflow.orchestrator import run
from audio_translate.workflow.postprocess import moderate, synthesize, translate
from tests.test_postprocess import FakeTranslator, FakeTTS


class EditionBase(unittest.TestCase):
    TIER = 'basic'

    def setUp(self):
        self.addCleanup(patch.stopall)
        patch('audio_translate.core.license_gate.assert_allowed', return_value=True).start()
        patch.object(edition, '_cached', self.TIER).start()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)/'data'
        self.root = self.data/'results'
        for module in (results, sealing): patch.object(module, 'DATA', self.data).start()
        patch.object(results, 'RESULTS', self.root).start()
        self.job_id = str(uuid.uuid4())
        self.job = self.data/'tmp'/self.job_id
        (self.job/'working').mkdir(parents=True); (self.job/'source').mkdir()
        states = initial_steps({})
        for step in STEPS[:2]: states[step]['state'] = 'COMPLETED'
        atomic_json(self.job/'job.json', {'id': self.job_id, 'status': 'QUEUED', 'name': 'Edition test', 'url': '',
                                          'created_at': '2026-10-06T00:00:00Z', 'steps': states})
        (self.job/'transcript.zh.jsonl').write_text(json.dumps({'start_ms': 0, 'end_ms': 900, 'text': '你好'}, ensure_ascii=False)+'\n', encoding='utf-8')
        (self.job/'transcript.zh.md').write_text('你好', encoding='utf-8')

    def run_all(self):
        rules = ReplacementRules(self.data/'config')
        def child(command, **kwargs):
            stage = command[-1]
            {'translation': lambda: translate(self.job, FakeTranslator()), 'moderation': lambda: moderate(self.job, rules),
             'tts': lambda: synthesize(self.job, FakeTTS())}[stage]()
            return Mock(returncode=0)
        with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=child):
            self.assertEqual(run(self.job), 0)
        return read_json(self.root/self.job_id/'outputs.json')['files']


class BasicTests(EditionBase):
    def test_basic_exports_and_working_files_keep_chinese_in_plaintext(self):
        files = self.run_all()
        self.assertTrue({'ZH_JSONL', 'ZH_MD'} <= {item['type'] for item in files})
        saved = self.root/self.job_id
        for item in files:
            self.assertEqual(file_digest(saved/item['path']), item['sha256'])
        vi = next(item for item in files if item['type'] == 'VI_JSONL')
        self.assertIn('text_zh', json.loads((saved/vi['path']).read_text(encoding='utf-8').splitlines()[0]))
        self.assertIn('你好', next((saved/item['path']).read_text(encoding='utf-8') for item in files if item['type'] == 'ZH_MD'))
        self.assertEqual(list(self.job.rglob('*.sealed')), [])
        for name in ['transcript.zh.jsonl', 'transcript.zh.md', 'transcript.vi.jsonl', 'transcript.vi.moderated.jsonl']:
            self.assertTrue((self.job/name).exists(), name)

    def test_basic_can_restart_from_download_and_has_no_chinese_gate(self):
        self.assertFalse(hasattr(edition, 'require_chinese_access'))
        self.run_all()
        (self.job/'source'/'audio.wav').write_bytes(b'RIFF')
        for step in ('TRANSCRIPTION', 'DOWNLOAD'):  # Transcription first: it needs a finished Download.
            atomic_json(self.job/'job.json', {**read_json(self.job/'job.json'), 'status': 'COMPLETED'})
            self.assertEqual(manage.reprocess(self.job_id, step)['id'], self.job_id)
            self.assertEqual(read_json(self.job/'job.json')['steps'][step]['state'], 'PENDING')

    def test_output_listing_offers_chinese_kinds_to_basic(self):
        kinds = {kind for items in results.output_files({'workflow_no': 1}).values() for kind, _, _ in items}
        self.assertTrue({'ZH_JSONL', 'ZH_MD'} <= kinds)


class SealedJobTests(EditionBase):
    """Jobs sealed by an earlier Basic build: unsealed once, then plaintext (no new sealing)."""

    def seal_like_the_old_build(self):
        import secrets
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = secrets.token_bytes(32)
        (self.data/'keys').mkdir(parents=True, exist_ok=True)
        (self.data/'keys'/'sealing.key').write_bytes(sealing._dpapi(key, True))
        for name in ['transcript.zh.jsonl', 'transcript.zh.md']:
            path = self.job/name; nonce = secrets.token_bytes(12)
            sealing.sealed(path).write_bytes(sealing.MAGIC + nonce + AESGCM(key).encrypt(nonce, path.read_bytes(), name.encode()))
            path.unlink()

    def test_old_sealed_files_are_unsealed_and_stay_plaintext(self):
        self.seal_like_the_old_build()
        self.assertFalse((self.job/'transcript.zh.jsonl').exists())
        with sealing.opened(self.job):
            self.assertIn('你好', (self.job/'transcript.zh.jsonl').read_text(encoding='utf-8'))
        self.assertTrue((self.job/'transcript.zh.jsonl').exists())
        self.assertEqual(list(self.job.rglob('*.sealed')), [])

    def test_tampered_sealed_file_is_rejected(self):
        self.seal_like_the_old_build()
        box = sealing.sealed(self.job/'transcript.zh.jsonl')
        raw = bytearray(box.read_bytes()); raw[-1] ^= 1; box.write_bytes(bytes(raw))
        with self.assertRaises(Exception): sealing.unseal(self.job)

    def test_missing_key_is_reported_not_recreated(self):
        self.seal_like_the_old_build()
        (self.data/'keys'/'sealing.key').unlink()
        with self.assertRaisesRegex(ValueError, 'sealing key'): sealing.unseal(self.job)
        self.assertFalse((self.data/'keys'/'sealing.key').exists())


class EditionDetectionTests(unittest.TestCase):
    def test_reads_native_identity_once_and_fails_closed(self):
        from audio_translate.core.license_gate import LicenseError
        with patch.object(edition, '_cached', None), patch('audio_translate.core.license_gate.native_command', side_effect=LicenseError('CORE_UNAVAILABLE')):
            self.assertEqual(edition.tier(), 'basic')
            self.assertIsNone(edition._cached)  # A transient failure is not remembered.
        with patch.object(edition, '_cached', None), patch('audio_translate.core.license_gate.native_command', return_value={'product_id': 'audio-translate'}) as native:
            self.assertEqual((edition.tier(), edition.tier()), ('plus', 'plus'))
            native.assert_called_once()
        with patch.object(edition, '_cached', None), patch('audio_translate.core.license_gate.native_command', return_value={'product_id': 'audio-translate-basic'}):
            self.assertTrue(edition.is_basic())


class PlusTests(EditionBase):
    TIER = 'plus'

    def test_plus_matches_basic_for_chinese_and_plaintext(self):
        files = self.run_all()
        self.assertTrue({'ZH_JSONL', 'ZH_MD'} <= {item['type'] for item in files})
        self.assertTrue((self.job/'transcript.zh.jsonl').exists())
        self.assertEqual(list(self.job.rglob('*.sealed')), [])


if __name__ == '__main__': unittest.main()
