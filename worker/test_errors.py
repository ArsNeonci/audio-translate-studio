"""Failure injection, durable retry admission and artifact preservation."""
import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from errors import STEPS, classify, fix_guide, initial_steps, record_failure, transition
from orchestrator import run
from retry import request_retry, cleanup
from storage import atomic_json, read_json, file_lock, LockedError, file_digest


class ErrorTests(unittest.TestCase):
    def setUp(self):
        license_patch = patch("license_gate.assert_allowed", return_value=True)
        license_patch.start()
        self.addCleanup(license_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name) / 'job'
        (self.job / 'working').mkdir(parents=True)
        atomic_json(self.job / 'job.json', {'status': 'QUEUED', 'steps': initial_steps({})})

    def test_each_failed_node_retries_without_any_predecessor(self):
        for step in STEPS:
            with self.subTest(step=step):
                states = initial_steps({})
                for previous in STEPS[:STEPS.index(step)]:
                    states[previous]['state'] = 'COMPLETED'
                atomic_json(self.job/'job.json', {'status': 'QUEUED', 'steps': states})
                with patch('postprocess.stage_complete', return_value=False), patch('orchestrator.subprocess.run', return_value=Mock(returncode=1)) as child:
                    self.assertEqual(run(self.job), 1)
                    self.assertEqual(child.call_count, 1)
                    self.assertEqual(child.call_args.args[0][-1], step.lower())
                failed = read_json(self.job/'job.json')
                self.assertEqual(failed['steps'][step]['state'], 'FAILED')
                with patch('postprocess.stage_complete', return_value=False):
                    request_retry(self.job, step)
                    with patch('orchestrator.subprocess.run', return_value=Mock(returncode=0)) as child:
                        self.assertEqual(run(self.job), 0)
                        self.assertEqual(child.call_count, 1)
                        self.assertEqual(child.call_args.args[0][-1], step.lower())
                saved = read_json(self.job/'job.json')
                self.assertEqual(saved['steps'][step]['state'], 'COMPLETED')
                self.assertEqual(saved['steps'][step]['retry_count'], 1)
                self.assertEqual(saved['steps'][step]['attempt'], 2)
                self.assertTrue(all(saved['steps'][p]['state'] == 'COMPLETED' for p in STEPS[:STEPS.index(step)]))

    def test_admission_checks_failed_predecessors_queue_and_os_lock(self):
        with self.assertRaises(ValueError): request_retry(self.job, 'DOWNLOAD')
        record_failure(self.job, 'TRANSLATION', RuntimeError('unknown'))
        with self.assertRaises(ValueError): request_retry(self.job, 'TRANSLATION')
        record_failure(self.job, 'DOWNLOAD', RuntimeError('unknown'))
        with file_lock(self.job/'working'/'worker.lock'):
            with self.assertRaises(LockedError): request_retry(self.job, 'DOWNLOAD')
        request_retry(self.job, 'DOWNLOAD')
        with self.assertRaises(ValueError): request_retry(self.job, 'DOWNLOAD')
        with self.assertRaises(ValueError): request_retry(self.job, '../source')

    def test_guides_unknown_errors_redaction_and_refresh_persistence(self):
        cases = [(ModuleNotFoundError('no module'), 'DEPENDENCY_MISSING'),
                 (FileNotFoundError('ffmpeg'), 'FFMPEG_MISSING'),
                 (FileNotFoundError('missing input'), 'PATH_MISSING'),
                 (PermissionError('denied'), 'FILE_PERMISSION'),
                 (OSError(errno.ENOSPC, 'disk full'), 'DISK_FULL'),
                 (RuntimeError('CUDA out of memory'), 'CUDA_OOM'),
                 (RuntimeError('invalid CUDA device'), 'CUDA_CONFIG'),
                 (RuntimeError('model not found'), 'MODEL_MISSING'),
                 (RuntimeError('YouTube needs cookies'), 'YOUTUBE_AUTH'),
                 (RuntimeError('HTTP 429'), 'RATE_LIMIT'),
                 (ValueError('invalid batch environment'), 'ENV_CONFIG')]
        for exc, code in cases:
            self.assertEqual(classify(exc), code)
            self.assertTrue(fix_guide(code)['checks_and_fixes'])
        self.assertIsNone(fix_guide('STEP_FAILED'))
        transition(self.job, 'DOWNLOAD', 'RUNNING')
        with patch.dict(os.environ, {'TEST_API_KEY': 'private-value-928'}):
            record_failure(self.job, 'DOWNLOAD', RuntimeError('cookie SID=private-cookie\nprivate-value-928 https://example.test/?password=abc'))
        text = (self.job/'errors.jsonl').read_text(encoding='utf-8')
        for secret in ['private-cookie', 'private-value-928', 'password=abc']:
            self.assertNotIn(secret, text)
        error = read_json(self.job/'job.json')['steps']['DOWNLOAD']['error']
        self.assertTrue(error['recoverable_manually'])
        self.assertEqual(error['error_code'], 'YOUTUBE_AUTH')
        self.assertEqual(json.loads(text)['attempt'], 1)

    def test_cleanup_scope_preserves_source_and_completed_outputs(self):
        (self.job/'source').mkdir()
        source = self.job/'source'/'audio.webm'
        source.write_bytes(b'original')
        upstream = self.job/'transcript.zh.jsonl'
        upstream.write_text('original', encoding='utf-8')
        (self.job/'transcript.vi.jsonl.tmp').write_text('broken')
        (self.job/'transcript.vi.jsonl').write_text('incomplete')
        (self.job/'transcript.vi.md').write_text('incomplete')
        with patch('postprocess.stage_complete', return_value=False): cleanup(self.job, 'TRANSLATION')
        self.assertFalse((self.job/'transcript.vi.jsonl.tmp').exists())
        self.assertFalse((self.job/'transcript.vi.jsonl').exists())
        self.assertEqual(source.read_bytes(), b'original')
        self.assertEqual(upstream.read_text(), 'original')
        output = self.job/'transcript.vi.jsonl'
        output.write_text('complete')
        with patch('postprocess.stage_complete', return_value=True): cleanup(self.job, 'TRANSLATION')
        self.assertEqual(output.read_text(), 'complete')

    def test_tts_retry_cleans_corruption_resumes_valid_segments_without_duplicates(self):
        from test_postprocess import FakeTranslator, FakeTTS
        from adapters import adapter_settings
        from postprocess import translate, moderate, synthesize
        from rules import ReplacementRules
        rows = [{'start_ms': i*1000, 'end_ms': i*1000+900, 'text': f'你好{i}'} for i in range(3)]
        (self.job/'transcript.zh.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
        adapter_settings(self.job)
        translate(self.job, FakeTranslator())
        moderate(self.job, ReplacementRules(Path(self.temp.name)/'config'))
        with self.assertRaises(RuntimeError): synthesize(self.job, FakeTTS(fail_after=1))
        valid = self.job/'voice'/'000001.wav'
        before = (file_digest(valid), valid.stat().st_mtime_ns)
        bad = self.job/'voice'/'000002.wav'
        bad.write_bytes(b'corrupted')
        orphan = self.job/'working'/'voice-checkpoints'/'000003.json'
        orphan.write_text('{broken')
        temp = self.job/'voice'/'temp'/'nested'
        temp.mkdir(parents=True)
        (temp/'bad.tmp').write_text('bad')
        input_sha = file_digest(self.job/'transcript.vi.moderated.jsonl')
        states = initial_steps({})
        for s in STEPS[:-1]: states[s]['state'] = 'COMPLETED'
        atomic_json(self.job/'job.json', {'status': 'FAILED', 'steps': states})
        transition(self.job, 'TTS', 'RUNNING')
        record_failure(self.job, 'TTS', RuntimeError('test failure'))
        request_retry(self.job, 'TTS')
        self.assertFalse(bad.exists())
        self.assertFalse(orphan.exists())
        self.assertFalse((temp/'bad.tmp').exists())
        resumed = FakeTTS()
        synthesize(self.job, resumed)
        self.assertEqual(len(resumed.calls), 2)
        self.assertEqual((file_digest(valid), valid.stat().st_mtime_ns), before)
        self.assertEqual(file_digest(self.job/'transcript.vi.moderated.jsonl'), input_sha)
        synthesize(self.job, FakeTTS(fail_after=0))
        manifest = [json.loads(line) for line in (self.job/'voice'/'voice.manifest.jsonl').read_text().splitlines()]
        self.assertEqual([r['index'] for r in manifest], [1, 2, 3])

    def test_asr_cleanup_keeps_valid_chunks_and_removes_corrupted_cache(self):
        valid = self.job/'working'/'chunk-000000.json'
        atomic_json(valid, [{'start_ms': 0, 'end_ms': 10, 'text': '你好'}])
        bad = self.job/'working'/'chunk-000001.json'
        bad.write_text('{unfinished')
        temp = self.job/'working'/'chunk-000002.json.random.tmp'
        temp.write_text('partial')
        cleanup(self.job, 'TRANSCRIPTION')
        self.assertTrue(valid.exists())
        self.assertFalse(bad.exists())
        self.assertFalse(temp.exists())

    def test_download_cleanup_removes_bad_final_but_keeps_resume_and_valid_source(self):
        (self.job/'source').mkdir()
        source = self.job/'source'/'audio.webm'
        part = self.job/'source'/'audio.webm.part'
        source.write_bytes(b'complete')
        part.write_bytes(b'resume')
        with patch('pipeline.duration_ms', return_value=1000): cleanup(self.job, 'DOWNLOAD')
        self.assertTrue(source.exists())
        with patch('pipeline.duration_ms', side_effect=FileNotFoundError('ffprobe')): cleanup(self.job, 'DOWNLOAD')
        self.assertTrue(source.exists())
        with patch('pipeline.duration_ms', side_effect=ValueError('invalid duration')): cleanup(self.job, 'DOWNLOAD')
        self.assertFalse(source.exists())
        self.assertEqual(part.read_bytes(), b'resume')


if __name__ == '__main__': unittest.main()
