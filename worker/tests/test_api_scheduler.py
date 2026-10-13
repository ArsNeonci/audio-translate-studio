"""The local API's scheduler (audio_translate/api/jobs.py, ported from lib/server/jobs.ts schedule()). Workflow processes,
the lane broker and the licence are faked; worker_failure writes real files in a temporary folder."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from audio_translate.api import jobs


class FakeProcess:
    def __init__(self): self.done, self.code = threading.Event(), None
    def finish(self, code): self.code = code; self.done.set()
    def wait(self): self.done.wait(10); return self.code


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.listed, self.commands, self.spawned, self.failures, self.soon = [], [], [], [], []
        self.denied, self.decision, self.current = None, {'status': 200, 'start': None}, {}
        def worker_command(script, payload):
            self.commands.append((script, payload))
            return self.decision if script == 'resources.py' else {'status': 200}
        def spawn(payload, stdout=None, stderr=None):
            self.spawned.append(payload); process = FakeProcess(); self.process = process; return process
        def folder(job_id): (self.root / job_id / 'working').mkdir(parents=True, exist_ok=True); return self.root / job_id
        self.scheduler = jobs.Scheduler()
        for p in (patch.object(jobs, 'list_jobs', lambda include_tools=False: list(self.listed)), patch.object(jobs, 'license_denial', lambda: self.denied),
                  patch.object(jobs, 'worker_command', worker_command), patch.object(jobs, 'spawn_security_core', spawn), patch.object(jobs, 'job_dir', folder),
                  patch.object(jobs, 'get_job', lambda job_id: self.current.get(job_id)),
                  patch.object(jobs, 'worker_failure', lambda job, code, message: self.failures.append((job['id'], code, message))),
                  patch.object(self.scheduler, 'soon', lambda delay=0.0: self.soon.append(delay)), patch.object(self.scheduler, '_retry_later', lambda: None)):
            p.start(); self.addCleanup(p.stop)

    def job(self, job_id, status='QUEUED', **extra): return {'id': job_id, 'status': status, 'created_at': f'2026-10-13T00:00:0{len(self.listed)}Z', **extra}

    def admitted(self): return [p for s, p in self.commands if s == 'resources.py']

    def test_nothing_waiting_asks_nobody(self):
        self.listed = [self.job('a', 'COMPLETED'), self.job('b', 'PAUSED'), self.job('c', 'FAILED')]
        self.scheduler.schedule()
        self.assertEqual((self.admitted(), self.spawned), ([], []))

    def test_without_a_licence_nothing_starts(self):
        self.listed = [self.job('a')]; self.denied = 'DENIED'
        self.scheduler.schedule()
        self.assertEqual((self.admitted(), self.spawned), ([], []))

    def test_the_broker_picks_and_the_job_starts_through_the_security_core(self):
        self.listed = [self.job('new'), self.job('old')]   # newest first, as list_jobs returns them
        self.decision = {'status': 200, 'start': 'old'}
        self.scheduler.schedule()
        self.assertEqual(self.admitted(), [{'action': 'admit', 'ids': ['old', 'new'], 'running': []}])   # oldest first
        self.assertEqual(self.spawned, [{'action': 'workflow', 'job_dir': str(self.root / 'old')}])
        self.assertEqual((self.scheduler.active_count(), self.soon), (1, [5]))
        # A running job is not offered again.
        self.scheduler.schedule()
        self.assertEqual(self.admitted()[-1]['ids'], ['new'])
        self.assertEqual(self.admitted()[-1]['running'], ['old'])

    def watch(self, status, code):
        self.listed = [self.job('a')]; self.decision = {'status': 200, 'start': 'a'}
        self.scheduler.schedule(); self.soon.clear()
        self.current['a'] = self.job('a', status)
        self.process.finish(code)
        for _ in range(200):
            if not self.scheduler.active_count(): break
            time.sleep(0.01)
        time.sleep(0.05)

    def test_a_worker_that_dies_marks_the_step_failed(self):
        self.watch('TRANSLATING', 3)
        self.assertEqual(self.failures, [('a', 'STEP_FAILED', 'Worker dừng với exit code 3. Xem working/worker.log.')])
        self.assertEqual(self.soon, [0.0])

    def test_a_clean_exit_after_finishing_schedules_the_next(self):
        self.watch('COMPLETED', 0)
        self.assertEqual((self.failures, self.soon), ([], [0.0]))

    def test_a_clean_exit_while_another_worker_owns_the_job_leaves_it_alone(self):
        self.watch('TRANSLATING', 0)
        self.assertEqual((self.failures, self.soon), ([], []))

    def test_a_failed_exit_of_a_stopped_job_is_not_a_failure(self):
        for status in ('PAUSED', 'CANCELLED', 'AWAITING_REVIEW'):
            self.failures.clear(); self.watch(status, 1)
            self.assertEqual(self.failures, [], status)

    def test_deletion_requests_are_finished_and_never_started(self):
        self.listed = [self.job('d', delete_requested=True), self.job('p', pause_requested=True)]
        self.scheduler.schedule()
        self.assertIn(('manage.py', {'action': 'finish_abort', 'id': 'd'}), self.commands)
        self.assertEqual(self.admitted(), [])

    def test_an_automatically_paused_job_is_offered_again(self):
        self.listed = [self.job('p', 'PAUSED', auto_paused_for='memory')]
        self.scheduler.schedule()
        self.assertEqual(self.admitted()[0]['ids'], ['p'])

    def test_a_resumed_job_triggers_a_quick_second_pass(self):
        self.listed = [self.job('p', 'PAUSED', auto_paused_for='memory')]; self.decision = {'status': 200, 'resumed': 'p'}
        self.scheduler.schedule()
        self.assertEqual((self.spawned, self.soon), ([], [0.5]))

    def test_one_pass_at_a_time(self):
        self.scheduler.running.acquire()
        try:
            self.listed = [self.job('a')]; self.decision = {'status': 200, 'start': 'a'}
            self.scheduler.schedule()
            self.assertEqual((self.admitted(), self.spawned), ([], []))
        finally: self.scheduler.running.release()

    def test_a_worker_that_cannot_start_is_recorded(self):
        self.listed = [self.job('a')]; self.decision = {'status': 200, 'start': 'a'}; self.current['a'] = self.job('a')
        with patch.object(jobs, 'spawn_security_core', side_effect=OSError('missing')):
            self.scheduler.schedule()
        self.assertEqual(self.failures, [('a', 'PATH_MISSING', 'Không chạy được Python worker. Kiểm tra PYTHON_BIN và .venv.')])
        self.assertEqual(self.scheduler.active_count(), 0)


class WorkerFailureTests(unittest.TestCase):
    def test_the_step_job_and_error_log_are_written(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(jobs, 'job_dir', lambda job_id: Path(temp)):
            job = {'id': 'a', 'status': 'TRANSLATING', 'active_stage': 'translation', 'run_started_at': '2026-10-13T00:00:00.000Z', 'total_duration_ms': 1000,
                   'steps': {s: {'state': 'COMPLETED' if s in ('DOWNLOAD', 'TRANSCRIPTION') else 'PENDING', 'attempt': 1, 'retry_count': 0} for s in jobs.STEPS},
                   'artifacts': {'zh': True}, 'pause_requested': False}
            job['steps']['TRANSLATION'].update(state='RUNNING', started_at='2026-10-13T00:00:00.000Z')
            jobs.worker_failure(job, 'STEP_FAILED', 'boom')
            saved = json.loads((Path(temp) / 'job.json').read_text(encoding='utf-8'))
            self.assertEqual((saved['status'], saved['failed_stage'], saved['error'], saved['active_stage'], saved['run_started_at']), ('FAILED', 'translation', 'boom', None, None))
            self.assertEqual(saved['steps']['TRANSLATION']['state'], 'FAILED')
            self.assertEqual(saved['steps']['TRANSLATION']['error']['error_code'], 'STEP_FAILED')
            self.assertGreater(saved['total_duration_ms'], 1000)
            self.assertNotIn('artifacts', saved); self.assertNotIn('pause_requested', saved)   # read-time fields are not stored
            line = json.loads((Path(temp) / 'errors.jsonl').read_text(encoding='utf-8').strip())
            self.assertEqual((line['step'], line['message'], line['attempt'], line['recoverable_manually']), ('TRANSLATION', 'boom', 1, False))


class TranscriptionViewTests(unittest.TestCase):
    def test_phases_from_the_parent_step(self):
        running = {'status': 'TRANSCRIBING', 'chunks_total': 4, 'chunks_done': 1,
                   'steps': {'TRANSCRIPTION': {'state': 'RUNNING', 'attempt': 1, 'started_at': '2026-10-13T00:00:00.000Z'}}}
        view = jobs.transcription_view(running, {'vad': '2026-10-13T00:00:10.000Z', 'chunks': '2026-10-13T00:00:30.000Z'})
        self.assertEqual([v['state'] for v in view], ['COMPLETED', 'COMPLETED', 'RUNNING', 'PENDING'])
        self.assertEqual([v['progress'] for v in view], [100, 100, 25.0, 0])
        self.assertEqual([v['duration_ms'] for v in view], [10000, 20000, None, None])
        self.assertEqual(view[2]['started_at'], '2026-10-13T00:00:30.000Z')
        done = jobs.transcription_view({'status': 'COMPLETED', 'steps': {'TRANSCRIPTION': {'state': 'COMPLETED', 'attempt': 2}}})
        self.assertEqual(([v['state'] for v in done], [v['duration_ms'] for v in done]), (['COMPLETED'] * 4, [None] * 4))
        recorded = [{'state': 'COMPLETED'}] * 4
        self.assertIs(jobs.transcription_view({'transcription_steps': recorded}), recorded)


if __name__ == '__main__':
    unittest.main()
