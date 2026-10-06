"""Basic edition: the run stops before paid Voice generation unless Auto; continue / finish / reprocess."""
from unittest.mock import patch

from audio_translate.core import edition
from audio_translate.core.storage import read_json, update_job
from audio_translate.workflow import manage
from tests.test_edition import EditionBase


class ReviewTests(EditionBase):
    def held(self, auto=False):
        update_job(self.job, tts_auto=auto, storage_scope='workflows')
        return self.run_all()

    def test_holds_before_tts_and_continue_generates_the_voice(self):
        self.held()
        job = read_json(self.job/'job.json')
        self.assertEqual(job['status'], 'AWAITING_REVIEW')
        self.assertEqual((job['steps']['MODERATION']['state'], job['steps']['TTS']['state']), ('COMPLETED', 'PENDING'))
        self.assertFalse((self.job/'voice.vi.wav').exists())
        self.assertEqual(manage.review(self.job_id, 'continue')['status'], 'QUEUED')
        files = self.run_all()
        self.assertEqual(read_json(self.job/'job.json')['status'], 'COMPLETED')
        self.assertIn('VOICE_WAV', {item['type'] for item in files})

    def test_finish_completes_without_voice_and_reprocess_from_tts_does_not_ask(self):
        self.held()
        job = manage.review(self.job_id, 'finish')
        self.assertEqual((job['status'], job['steps']['TTS']['state'], job['review_skipped']), ('COMPLETED', 'SKIPPED', True))
        with self.assertRaisesRegex(ValueError, 'not waiting'): manage.review(self.job_id, 'continue')
        job = manage.reprocess(self.job_id, 'TTS')
        self.assertTrue(job['review_approved'])
        self.run_all()
        self.assertEqual(read_json(self.job/'job.json')['status'], 'COMPLETED')
        self.assertTrue(read_json(self.job/'job.json')['steps']['TTS']['state'] == 'COMPLETED')

    def test_reprocess_from_an_earlier_stage_asks_again(self):
        self.held(); manage.review(self.job_id, 'continue'); self.run_all()
        manage.reprocess(self.job_id, 'MODERATION')
        self.run_all()
        self.assertEqual(read_json(self.job/'job.json')['status'], 'AWAITING_REVIEW')

    def test_auto_runs_straight_through(self):
        self.held(auto=True)
        self.assertEqual(read_json(self.job/'job.json')['status'], 'COMPLETED')

    def test_create_records_auto_only_for_basic_runs_with_voice(self):
        with patch('audio_translate.tts.voices.select', return_value='Ngọc Huyền'), patch.object(manage, 'DATA', self.data), \
             patch('audio_translate.workflow.results.metadata'):
            job = manage.create('https://youtu.be/1JzKgwOESoM')
            self.assertIs(job['tts_auto'], False)
            self.assertIs(manage.create('https://youtu.be/1JzKgwOESoM', auto=True)['tts_auto'], True)
            with patch.object(edition, '_cached', 'plus'):
                self.assertNotIn('tts_auto', manage.create('https://youtu.be/1JzKgwOESoM'))

    def test_jobs_without_the_setting_are_never_held(self):
        self.assertFalse(manage.needs_review({'status': 'QUEUED'}))
        self.assertTrue(manage.needs_review({'tts_auto': False}))
        self.assertFalse(manage.needs_review({'tts_auto': False, 'tool_steps': ['TRANSLATION']}))
        self.assertFalse(manage.needs_review({'tts_auto': False, 'review_approved': True}))


if __name__ == '__main__':
    import unittest; unittest.main()
