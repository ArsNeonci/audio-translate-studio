"""Subtitles inside runs: every new workflow ends with the .srt of its voice, tool 6 makes one from a finished voice, Reprocess adds or redoes it
(an older workflow gains the step), and burning the subtitles into the picture needs the confirmation and really draws them."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from audio_translate.core.storage import read_json
from audio_translate.workflow import manage, results
from audio_translate.video import merge
from tests import test_management, test_video_workflow
from tests.test_video_merge import FFMPEG, clip


class SubtitleWorkflowTests(unittest.TestCase):
    setUp = test_management.ManagementTests.setUp
    prepare = test_management.ManagementTests.prepare
    child = test_video_workflow.VideoWorkflowTests.child
    run_all = test_video_workflow.VideoWorkflowTests.run_all
    video = test_video_workflow.VideoWorkflowTests.video

    def finished(self, **extra):
        job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice, **extra)
        d = results.workspace(job['id']); self.prepare(d); self.run_all(d)
        return job, d

    def srt_of(self, d):
        out = results.destination(d.name)
        item = next(f for f in read_json(out / 'outputs.json')['files'] if f['type'] == 'SUBTITLE_SRT')
        return item, (out / item['path']).read_text(encoding='utf-8')

    def test_a_new_workflow_ends_with_its_srt_timed_from_the_voice(self):
        job, d = self.finished()
        self.assertEqual(job['subtitle'], {'max_chars': 84, 'min_seconds': 1.0})
        saved = read_json(d / 'job.json')
        self.assertEqual((saved['status'], saved['steps']['SUBTITLE']['state']), ('COMPLETED', 'COMPLETED'))
        item, text = self.srt_of(d)
        self.assertEqual((item['step'], item['path'], item['status']), ('SUBTITLE', 'subtitle/000001-voice.vi.srt', 'AVAILABLE'))
        self.assertTrue(text.startswith('1\n00:00:00,000 --> '))
        manifest = [json.loads(l) for l in (d / 'voice' / 'voice.manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(isinstance(row['frames'], int) and row['frames'] > 0 for row in manifest))      # recorded for the subtitles
        self.assertNotIn('\r', text)

    def test_the_settings_chosen_at_the_start_are_used(self):
        job, d = self.finished(subtitle={'max_chars': 30, 'min_seconds': 2})
        self.assertEqual(read_json(d / 'job.json')['subtitle'], {'max_chars': 30, 'min_seconds': 2.0})
        with self.assertRaises(ValueError): manage.create('https://youtu.be/1JzKgwOESoM', self.voice, subtitle={'max_chars': 5})

    def test_reprocess_redoes_the_srt_only_and_an_older_workflow_gains_the_step(self):
        job, d = self.finished()
        manage.reprocess(job['id'], 'SUBTITLE', subtitle={'max_chars': 40})
        self.assertEqual(self.run_all(d), ['subtitle'])                                         # voice, text and the rest are untouched
        self.assertEqual(read_json(d / 'job.json')['subtitle']['max_chars'], 40)
        old, od = self.finished()
        saved = read_json(od / 'job.json'); saved.pop('subtitle'); saved['steps'].pop('SUBTITLE')
        (od / 'job.json').write_text(json.dumps(saved), encoding='utf-8')                       # as if made by 3.0.0: five steps
        self.assertNotIn('SUBTITLE', manage.effective_steps(read_json(od / 'job.json')))
        manage.reprocess(old['id'], 'SUBTITLE')
        self.assertEqual(self.run_all(od), ['subtitle'])
        self.assertEqual(read_json(od / 'job.json')['status'], 'COMPLETED')
        self.assertIn('SUBTITLE_SRT', [f['type'] for f in read_json(results.destination(od.name) / 'outputs.json')['files'] if f['status'] == 'AVAILABLE'])

    def test_tool_6_makes_the_srt_of_a_finished_voice_and_refuses_anything_else(self):
        job, d = self.finished()
        tool = manage.create(tool='subtitle', voice_job=job['id'], subtitle={'max_chars': 50})
        t = results.workspace(tool['id'])
        self.assertEqual((tool['tool_steps'], tool['subtitle_voice']['job_id'], tool['subtitle']['max_chars']), (['SUBTITLE'], job['id'], 50))
        self.assertEqual(self.run_all(t), ['subtitle'])
        self.assertEqual(read_json(t / 'job.json')['status'], 'COMPLETED')
        _, text = self.srt_of(t)
        self.assertEqual(text.count('\n\n'), len([c for c in text.split('\n\n') if c.strip()]))
        for bad in ('not-an-id', tool['id'], None):
            with self.assertRaises(ValueError, msg=str(bad)): manage.create(tool='subtitle', voice_job=bad)
        # The workspace of the voice is gone (cleaned up): the published manifest and voice are enough.
        import shutil
        shutil.rmtree(d / 'voice')
        again = manage.create(tool='subtitle', voice_job=job['id'])
        self.assertEqual(self.run_all(results.workspace(again['id'])), ['subtitle'])

    def test_skipping_the_voice_skips_the_subtitles_too(self):
        with patch.object(manage, 'needs_review', lambda job: False):
            job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice)
        d = results.workspace(job['id']); self.prepare(d)
        update = read_json(d / 'job.json'); update['status'] = 'AWAITING_REVIEW'; update['tts_auto'] = False
        (d / 'job.json').write_text(json.dumps(update), encoding='utf-8')
        done = manage.review(job['id'], 'finish')
        self.assertEqual((done['status'], done['steps']['SUBTITLE']['state']), ('COMPLETED', 'SKIPPED'))

    @unittest.skipUnless(FFMPEG, 'ffmpeg is not on PATH')
    def test_burning_needs_the_confirmation_and_really_draws_the_text(self):
        job, d = self.finished()
        settings = self.video(1)
        with self.assertRaises(ValueError): merge.validate({**settings, 'burn': True})                        # not confirmed
        with self.assertRaises(ValueError): manage.create(tool='video', voice_job=job['id'], video={**settings, 'burn': True})
        plain = manage.create(tool='video', voice_job=job['id'], video=settings)
        burned = manage.create(tool='video', voice_job=job['id'], video={**settings, 'burn': True, 'burn_confirmed': True, 'subtitle': {'max_chars': 40}})
        frames = {}
        for name, run in (('plain', plain), ('burned', burned)):
            w = results.workspace(run['id']); self.run_all(w)
            out = results.destination(w.name)
            item = next(f for f in read_json(out / 'outputs.json')['files'] if f['type'] == 'VIDEO_MP4')
            target = Path(self.temp.name) / f'{name}.png'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(out / item['path']), '-frames:v', '1', str(target)], check=True)
            frames[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        self.assertEqual(read_json(results.workspace(burned['id']) / 'job.json')['video_plan']['mode'], 'encode')   # the picture was re-encoded
        self.assertEqual(read_json(results.workspace(plain['id']) / 'job.json')['video_plan']['mode'], 'copy')
        self.assertNotEqual(frames['plain'], frames['burned'])
        self.assertFalse((results.workspace(burned['id']) / 'working' / 'video-sub.srt').exists())                  # the helper file is removed


if __name__ == '__main__':
    unittest.main()
