"""Video merge inside runs: a workflow with videos gains a sixth step that publishes the video (moved, not copied) and asks the window
to open it; tool 5 takes the voice of a finished run; Reprocess can add or change the videos of a finished workflow."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from audio_translate.core.storage import read_json
from audio_translate.video.merge import merge
from audio_translate.workflow import manage, results
from audio_translate.workflow.orchestrator import run
from audio_translate.workflow.postprocess import moderate, synthesize, translate
from tests import test_management
from tests.test_postprocess import FakeTranslator, FakeTTS
from tests.test_video_merge import FFMPEG, clip

REAL_RUN = subprocess.run   # ffprobe inside the merge must still run; only the orchestrator's stage processes are replaced


@unittest.skipUnless(FFMPEG, 'ffmpeg is not on PATH')
class VideoWorkflowTests(unittest.TestCase):
    setUp = test_management.ManagementTests.setUp
    prepare = test_management.ManagementTests.prepare

    def child(self, d, seen):
        def execute(command, **kwargs):
            if '--stage' not in command: return REAL_RUN(command, **kwargs)
            stage = command[-1]; seen.append(stage)
            if stage == 'translation': translate(d, FakeTranslator())
            elif stage == 'moderation': moderate(d, self.rules)
            elif stage == 'tts': synthesize(d, FakeTTS())
            elif stage == 'subtitle':
                from audio_translate.video.subtitles import run as build_subtitles
                build_subtitles(d)
            elif stage == 'video': merge(d)
            elif stage == 'burn':
                from audio_translate.video.merge import burn
                burn(d)
            else: raise AssertionError('Unexpected stage ' + stage)
            return Mock(returncode=0)
        return execute

    def run_all(self, d):
        seen = []
        with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=self.child(d, seen)): self.assertEqual(run(d), 0)
        return seen

    def video(self, *seconds):
        return {'files': [{'path': clip(Path(self.temp.name) / f'clip{i}.mp4', s)} for i, s in enumerate(seconds)], 'resolution': 'keep', 'quality': 'high'}

    def test_a_workflow_with_videos_ends_with_the_merged_video(self):
        job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice, video=self.video(1))
        d = results.workspace(job['id']); self.prepare(d)
        self.assertEqual(self.run_all(d), ['translation', 'moderation', 'tts', 'subtitle', 'video'])
        saved = read_json(d / 'job.json')
        self.assertEqual((saved['status'], saved['steps']['VIDEO']['state'], saved['progress']), ('COMPLETED', 'COMPLETED', 100))
        out = results.destination(d.name)
        item = next(f for f in read_json(out / 'outputs.json')['files'] if f['type'] == 'VIDEO_MP4')
        self.assertEqual((item['step'], item['path'], item['status']), ('VIDEO', 'video/000001-video.vi.mp4', 'AVAILABLE'))
        self.assertTrue((out / item['path']).is_file())
        self.assertFalse((d / 'video.vi.mp4').exists())                      # moved into the results, not copied
        self.assertTrue((d / 'working' / 'video-open.pending').exists())      # the open window shows it once
        listed = next(j for j in manage.history('workflows') if j['id'] == job['id'])
        self.assertIn('VIDEO_MP4', [f['type'] for f in listed['files']])
        # Running the finished workflow again does not need the moved file.
        self.assertEqual(self.run_all(d), [])

    def test_a_workflow_without_videos_has_no_video_step(self):
        job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice)
        d = results.workspace(job['id']); self.prepare(d)
        self.assertEqual(self.run_all(d), ['translation', 'moderation', 'tts', 'subtitle'])
        self.assertNotIn('VIDEO', read_json(d / 'job.json')['steps'])

    def test_reprocess_adds_videos_to_a_finished_workflow_and_tool_5_reuses_its_voice(self):
        job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice)
        d = results.workspace(job['id']); self.prepare(d); self.run_all(d)
        with self.assertRaises(ValueError): manage.reprocess(job['id'], 'VIDEO')                 # no videos chosen
        manage.reprocess(job['id'], 'VIDEO', video=self.video(1, 1))
        self.assertEqual(self.run_all(d), ['video'])                                             # only the new step runs
        self.assertEqual(read_json(d / 'job.json')['steps']['TTS']['state'], 'COMPLETED')
        # Tool 6 lays the same voice over other clips; the workflow's own files are untouched.
        tool = manage.create(tool='video', voice_job=job['id'], video=self.video(2))
        t = results.workspace(tool['id'])
        self.assertEqual((tool['tool_steps'], tool['video_voice']['job_id']), (['VIDEO'], job['id']))
        self.assertEqual(self.run_all(t), ['video'])
        out = results.destination(t.name)
        self.assertTrue(any(f['type'] == 'VIDEO_MP4' and f['status'] == 'AVAILABLE' for f in read_json(out / 'outputs.json')['files']))
        with self.assertRaises(ValueError): manage.create(tool='video', voice_job=tool['id'], video=self.video(1))   # a video run has no voice to give
        with self.assertRaises(ValueError): manage.create(tool='video', voice_job='not-an-id', video=self.video(1))

    def test_a_moved_clip_fails_the_step_with_a_guide_and_retry_works_once_it_is_back(self):
        settings = self.video(1)
        job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice, video=settings)
        d = results.workspace(job['id']); self.prepare(d)
        path = Path(settings['files'][0]['path']); hidden = path.with_suffix('.away')
        path.rename(hidden)
        with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=self.child(d, [])): self.assertEqual(run(d), 1)
        failed = read_json(d / 'job.json')
        self.assertEqual((failed['status'], failed['steps']['VIDEO']['error']['error_code']), ('FAILED', 'VIDEO_MISSING'))
        hidden.rename(path)
        from audio_translate.workflow.retry import request_retry
        request_retry(d, 'VIDEO', fresh=True)
        self.assertEqual(self.run_all(d), ['video'])
        self.assertEqual(read_json(d / 'job.json')['status'], 'COMPLETED')


if __name__ == '__main__':
    unittest.main()
