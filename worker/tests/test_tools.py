"""Standalone tools: link input, forms of address in Tool 2, drain-then-delete while active."""
from pathlib import Path
from unittest.mock import patch
import unittest

from audio_translate.core.storage import atomic_json, read_json
from audio_translate.workflow import manage, results
from audio_translate.workflow.orchestrator import run
from audio_translate.workflow.postprocess import translation_signature, tool_addresser
from tests import test_management


class ToolTests(unittest.TestCase):
    # Same isolated data/registry fixture as the management tests, without re-running them.
    setUp = test_management.ManagementTests.setUp
    upload = test_management.ManagementTests.upload
    job = test_management.ManagementTests.job

    def test_transcription_tool_from_youtube_link_downloads_then_stops(self):
        job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice, tool='transcription')
        directory = results.workspace(job['id'])
        saved = read_json(directory / 'job.json')
        self.assertEqual(saved['tool_steps'], ['DOWNLOAD', 'TRANSCRIPTION'])
        self.assertEqual((saved['storage_scope'], saved['url'], saved['input_file']), ('tools', 'https://youtu.be/1JzKgwOESoM', None))
        self.assertTrue(directory.is_relative_to(self.data / 'tool-tmp'))

    def test_only_transcription_accepts_a_link(self):
        with self.assertRaisesRegex(ValueError, 'Only Chinese audio'):
            manage.create('https://youtu.be/1JzKgwOESoM', self.voice, tool='translation')

    def test_translation_tool_keeps_address_profile_and_signs_it(self):
        directory = self.upload()
        job = read_json(directory / 'job.json'); job['selected_address_profile'] = 'survival'
        atomic_json(directory / 'job.json', job)
        config = {'backend': 'fake'}
        with patch('audio_translate.workflow.postprocess.tool_addresser', return_value=type('A', (), {'signature': 'addr'})()):
            signed = translation_signature(directory, directory / 'transcript.zh.jsonl', config)
        with patch('audio_translate.workflow.postprocess.tool_addresser', return_value=None):
            plain = translation_signature(directory, directory / 'transcript.zh.jsonl', config)
        self.assertNotEqual(signed, plain)

    def test_workflows_never_use_the_tool_addresser(self):
        self.assertIsNone(tool_addresser(self.job()))

    def test_a_tool_can_be_stopped_continued_and_run_again_like_a_workflow(self):
        directory = self.upload()
        steps = read_json(directory / 'job.json')['tool_steps']
        self.assertEqual(steps, ['TRANSLATION'])
        # Stop: a queued tool stops at once and keeps what it has; Continue queues it again from where it stopped.
        manage.cancel(directory.name, 'pause')
        self.assertEqual(read_json(directory / 'job.json')['status'], 'PAUSED')
        manage.resume(directory.name)
        self.assertEqual(read_json(directory / 'job.json')['status'], 'QUEUED')
        self.assertFalse((directory / 'working' / 'cancel.signal').exists())
        # Run again: a finished tool starts over from its first step, the other results of the run untouched.
        job = read_json(directory / 'job.json')
        job['steps']['TRANSLATION'].update(state='COMPLETED'); job['status'] = 'COMPLETED'
        atomic_json(directory / 'job.json', job)
        again = manage.reprocess(directory.name, steps[0])
        self.assertEqual((again['status'], again['steps']['TRANSLATION']['state']), ('QUEUED', 'PENDING'))
        self.assertEqual((again['storage_scope'], again['tool_steps']), ('tools', ['TRANSLATION']))

    def test_delete_queued_tool_stops_then_removes_everything(self):
        directory = self.upload()
        number = read_json(directory / 'job.json')['workflow_no']
        result = manage.delete(directory.name, number, 'tools')
        self.assertTrue(result['deleted'])
        self.assertFalse(directory.exists())

    def test_delete_running_tool_drains_current_task_first(self):
        directory = self.upload()
        number = read_json(directory / 'job.json')['workflow_no']
        from audio_translate.core.storage import file_lock
        with file_lock(directory / 'working' / 'worker.lock'):  # the worker holds its lock while running
            atomic_json(directory / 'job.json', {**read_json(directory / 'job.json'), 'status': 'TRANSLATING'})
            result = manage.delete(directory.name, number, 'tools')
        self.assertEqual(result, {'deleted': False, 'deletion_pending': True})
        self.assertEqual(read_json(directory / 'working' / 'cancel.signal')['mode'], 'pause')  # finish the mini task
        self.assertTrue((directory / 'working' / 'delete-request.json').exists())
        atomic_json(directory / 'job.json', {**read_json(directory / 'job.json'), 'status': 'PAUSED'})
        self.assertEqual(manage.finish_abort(directory.name), {'deleted': True})
        self.assertFalse(directory.exists())

    def test_running_workflow_delete_still_requires_a_stop(self):
        directory = self.job()
        atomic_json(directory / 'job.json', {**read_json(directory / 'job.json'), 'status': 'TRANSLATING'})
        with self.assertRaisesRegex(ValueError, 'Pause'):
            manage.delete(directory.name, read_json(directory / 'job.json')['workflow_no'], 'workflows')


if __name__ == '__main__':
    unittest.main()
