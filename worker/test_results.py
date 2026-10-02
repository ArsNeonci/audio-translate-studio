"""Result publishing, atomic failure safety and retry isolation."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

import results
from errors import STEPS, initial_steps, record_failure
from orchestrator import run
from postprocess import translate, moderate, synthesize
from retry import request_retry
from rules import ReplacementRules
from storage import atomic_json, file_digest, read_json
from test_postprocess import FakeTranslator, FakeTTS


class ResultsTests(unittest.TestCase):
    def setUp(self):
        license_patch = patch("license_gate.assert_allowed", return_value=True)
        license_patch.start()
        self.addCleanup(license_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)/'data'
        self.root = self.data/'results'
        self.job_id = str(uuid.uuid4())
        self.job = self.data/'tmp'/self.job_id
        (self.job/'working').mkdir(parents=True)
        states = initial_steps({})
        for step in STEPS[:2]: states[step]['state'] = 'COMPLETED'
        atomic_json(self.job/'job.json', {'id': self.job_id, 'status': 'QUEUED', 'name': 'Result test',
            'url': 'https://youtu.be/1JzKgwOESoM', 'created_at': '2026-10-02T00:00:00Z', 'steps': states})
        (self.job/'transcript.zh.jsonl').write_text(json.dumps({'start_ms':0, 'end_ms':900, 'text':'你好'}, ensure_ascii=False)+'\n', encoding='utf-8')
        (self.job/'transcript.zh.md').write_text('你好', encoding='utf-8')
        self.addCleanup(patch.stopall)
        patch.object(results, 'DATA', self.data).start()
        patch.object(results, 'RESULTS', self.root).start()

    def test_orchestrator_automatically_publishes_all_steps_and_metadata(self):
        rules = ReplacementRules(self.data/'config')
        def child(command, **kwargs):
            stage = command[-1]
            if stage == 'translation': translate(self.job, FakeTranslator())
            elif stage == 'moderation': moderate(self.job, rules)
            elif stage == 'tts': synthesize(self.job, FakeTTS())
            else: self.fail('Reran completed predecessor')
            return Mock(returncode=0)
        (self.job/'working'/'abandoned.tmp').write_text('incomplete')
        with patch('orchestrator.subprocess.run', side_effect=child):
            self.assertEqual(run(self.job), 0)
        saved = self.root/self.job_id
        self.assertEqual(read_json(saved/'job.json')['status'], 'COMPLETED')
        self.assertEqual(read_json(saved/'source.json')['url'], 'https://youtu.be/1JzKgwOESoM')
        entries = read_json(saved/'outputs.json')['files']
        self.assertEqual(len(entries), 9)
        for item in entries:
            self.assertFalse(Path(item['path']).is_absolute())
            self.assertEqual(file_digest(saved/item['path']), item['sha256'])
        self.assertEqual(list(saved.rglob('*.tmp')), [])
        self.assertFalse((self.job/'working'/'abandoned.tmp').exists())
        before = {item['path']: (file_digest(saved/item['path']), (saved/item['path']).stat().st_mtime_ns) for item in entries}
        # Idempotent publication and a fresh index read simulate process restart.
        results.import_existing(self.job)
        self.assertEqual(before, {item['path']: (file_digest(saved/item['path']), (saved/item['path']).stat().st_mtime_ns) for item in entries})

    def test_atomic_copy_failure_keeps_previous_published_files(self):
        results.publish_step(self.job, 'TRANSCRIPTION')
        saved = self.root/self.job_id
        before = {p.relative_to(saved).as_posix(): file_digest(p) for p in saved.rglob('*') if p.is_file()}
        (self.job/'transcript.zh.md').write_text('new final', encoding='utf-8')
        def fail(inp, out, length):
            out.write(b'incomplete')
            raise OSError('simulated publication failure')
        with patch('results.shutil.copyfileobj', side_effect=fail):
            with self.assertRaises(OSError): results.publish_step(self.job, 'TRANSCRIPTION')
        self.assertEqual(before, {p.relative_to(saved).as_posix(): file_digest(p) for p in saved.rglob('*') if p.is_file()})
        self.assertEqual(list((self.job/'publication').glob('*.tmp')), [])
        results.publish_step(self.job, 'TRANSCRIPTION')
        self.assertEqual((saved/'transcription'/'transcript.zh.md').read_text(encoding='utf-8'), 'new final')

    def test_retry_never_deletes_completed_results(self):
        results.publish_step(self.job, 'TRANSCRIPTION')
        saved = self.root/self.job_id/'transcription'
        before = {p.name:file_digest(p) for p in saved.iterdir()}
        record_failure(self.job, 'TRANSLATION', RuntimeError('controlled failure'))
        (self.job/'transcript.vi.jsonl.tmp').write_text('incomplete')
        request_retry(self.job, 'TRANSLATION')
        self.assertEqual(before, {p.name:file_digest(p) for p in saved.iterdir()})
        self.assertFalse((self.job/'transcript.vi.jsonl.tmp').exists())
        self.assertEqual(read_json(self.root/self.job_id/'job.json')['status'], 'QUEUED')

    def test_legacy_import_is_read_only_and_does_not_load_models(self):
        old = self.data/'jobs'/self.job_id
        old.parent.mkdir()
        self.job.rename(old)
        before = read_json(old/'job.json')
        with patch('adapters.TranslationAdapter.load', side_effect=AssertionError('model loaded')):
            results.import_existing(old)
        self.assertEqual(read_json(old/'job.json'), before)
        self.assertEqual(len(read_json(self.root/self.job_id/'outputs.json')['files']), 2)
        self.assertEqual(results.workspace(self.job_id), old)

    def test_storage_overlap_and_invalid_job_ids_are_rejected(self):
        with self.assertRaises(ValueError): results.destination('../escape')
        with patch.object(results, 'RESULTS', self.data/'tmp'):
            with self.assertRaises(ValueError): results.destination(self.job_id)

    def test_startup_backfill_preserves_already_published_generation(self):
        results.publish_step(self.job, 'TRANSCRIPTION')
        (self.job/'transcript.zh.md').write_text('working copy changed', encoding='utf-8')
        results.import_existing(self.job)
        self.assertEqual((self.root/self.job_id/'transcription'/'transcript.zh.md').read_text(encoding='utf-8'), '你好')


if __name__ == '__main__': unittest.main()
