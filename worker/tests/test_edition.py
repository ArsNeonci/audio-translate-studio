"""Basic edition: no Chinese exports, encrypted working copies, blocked Chinese entry points."""
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
        (self.job/'working').mkdir(parents=True)
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
    def test_exports_have_no_chinese_and_working_copies_are_sealed(self):
        files = self.run_all()
        kinds = {item['type'] for item in files}
        self.assertFalse(kinds & {'ZH_JSONL', 'ZH_MD'})
        saved = self.root/self.job_id
        for item in files:
            self.assertEqual(file_digest(saved/item['path']), item['sha256'])
            if item['path'].endswith('.jsonl') and 'voice' not in item['path']:
                for line in (saved/item['path']).read_text(encoding='utf-8').splitlines():
                    self.assertNotIn('text_zh', json.loads(line))
        self.assertEqual([p for p in saved.rglob('*') if 'transcript.zh' in p.name], [])
        for name in ['transcript.zh.jsonl', 'transcript.zh.md', 'transcript.vi.jsonl', 'transcript.vi.moderated.jsonl', 'working/postprocess.sqlite3']:
            self.assertFalse((self.job/name).exists(), name)
            self.assertTrue(sealing.sealed(self.job/name).exists(), name)
            self.assertNotIn('你好'.encode(), sealing.sealed(self.job/name).read_bytes())

    def test_unseal_restores_exact_bytes_and_done_markers_stay_valid(self):
        self.run_all()
        from audio_translate.workflow.postprocess import stage_complete
        with sealing.opened(self.job):
            self.assertEqual(read_json(self.job/'job.json')['status'], 'COMPLETED')
            for stage in ['translation', 'moderation', 'tts']: self.assertTrue(stage_complete(self.job, stage), stage)
        self.assertFalse((self.job/'transcript.zh.jsonl').exists())

    def test_tampered_sealed_file_is_rejected(self):
        sealing.seal(self.job)
        box = sealing.sealed(self.job/'transcript.zh.jsonl')
        raw = bytearray(box.read_bytes()); raw[-1] ^= 1; box.write_bytes(bytes(raw))
        with self.assertRaises(Exception): sealing.unseal(self.job)

    def test_chinese_entry_points_are_blocked(self):
        with self.assertRaisesRegex(ValueError, 'Basic edition'):
            manage.create(tool='transcription', url='https://youtu.be/1JzKgwOESoM')
        for step in ('DOWNLOAD', 'TRANSCRIPTION'):
            with self.assertRaisesRegex(ValueError, 'Basic edition'): manage.reprocess(self.job_id, step)

    def test_listing_never_offers_chinese_kinds(self):
        # History and file resolution only list kinds from output_files().
        self.assertFalse({kind for items in results.output_files({'workflow_no': 1}).values() for kind, _, _ in items} & results.CHINESE_KINDS)


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

    def test_plus_keeps_chinese_and_plaintext(self):
        files = self.run_all()
        self.assertTrue({'ZH_JSONL', 'ZH_MD'} <= {item['type'] for item in files})
        vi = next(item for item in files if item['type'] == 'VI_JSONL')
        self.assertIn('text_zh', json.loads((self.root/self.job_id/vi['path']).read_text(encoding='utf-8').splitlines()[0]))
        self.assertTrue((self.job/'transcript.zh.jsonl').exists())
        self.assertEqual(list(self.job.rglob('*.sealed')), [])

    def test_upgrade_reads_jobs_sealed_by_basic(self):
        with patch.object(edition, '_cached', 'basic'):
            self.assertEqual(sealing.seal(self.job), 2)
        with sealing.opened(self.job):
            self.assertIn('你好', (self.job/'transcript.zh.jsonl').read_text(encoding='utf-8'))
        self.assertTrue((self.job/'transcript.zh.jsonl').exists())  # Plus does not re-seal.


if __name__ == '__main__': unittest.main()
