import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_translate.core import lanes
from audio_translate.core.lanes import GIB, allocate
from audio_translate.core.storage import atomic_json, read_json


def lease(name, order, demand=8, units=1, unit=GIB, base=0, **extra):
    return dict(id=name, order=order, demand=demand, units=units, unit_bytes=unit, base_bytes=base, **extra)


class AllocationTests(unittest.TestCase):
    def targets(self, leases, available=100 * GIB, cores=64):
        plans = allocate(leases, available, cores, 2 * GIB, now=1000)
        return [plans[item['id']]['target'] for item in sorted(leases, key=lambda item: item['order'])]

    def test_single_workflow_keeps_its_own_maximum(self):
        self.assertEqual(self.targets([lease('a', 1, demand=6)], available=0), [6])

    def test_spread_is_even_and_earlier_workflows_get_the_extra_unit(self):
        workflows = [lease(n, i, units=0) for i, n in enumerate('abc')]
        # 7 units of RAM after the reserve: 3-2-2; 8 units: 3-3-2.
        self.assertEqual(self.targets(workflows, available=9 * GIB), [3, 2, 2])
        self.assertEqual(self.targets(workflows, available=10 * GIB), [3, 3, 2])

    def test_minimum_one_unit_and_cores_bound_the_total(self):
        workflows = [lease(n, i, units=0) for i, n in enumerate('abc')]
        self.assertEqual(self.targets(workflows, cores=4), [2, 1, 1])

    def test_unused_share_is_redistributed(self):
        workflows = [lease('a', 1, demand=1, units=0), lease('b', 2, demand=8, units=0)]
        self.assertEqual(self.targets(workflows, available=7 * GIB), [1, 4])

    def test_light_stage_holds_no_units(self):
        workflows = [lease('a', 1, demand=0, units=0, base=GIB // 2), lease('b', 2, units=0)]
        # 6 free + 0.5 held - 2 reserve - 0.5 base = 4 units.
        self.assertEqual(self.targets(workflows, available=6 * GIB), [0, 4])

    def test_held_memory_is_reclaimable_budget(self):
        # Both use 3 units now with no free RAM beyond the reserve: they rebalance, not starve.
        workflows = [lease('a', 1, units=3), lease('b', 2, units=3)]
        self.assertEqual(self.targets(workflows, available=2 * GIB), [3, 3])

    def test_waiting_earlier_workflow_shrinks_and_then_pauses_the_latest(self):
        workflows = [lease('a', 1, units=1, waiting_bytes=GIB, waiting_since=995),
                     lease('b', 2, units=3), lease('c', 3, units=2)]
        plans = allocate(workflows, 2 * GIB, 64, 2 * GIB, now=1000)
        self.assertEqual([plans[n]['target'] for n in 'bc'], [1, 1])
        self.assertTrue(plans['a']['keep_waiting'])
        self.assertEqual(plans['c']['yielding_for'], 'a')
        self.assertFalse(any(plans[n]['pause'] for n in 'abc'))
        plans = allocate(workflows, 2 * GIB, 64, 2 * GIB, now=1000 + 2 * lanes.YIELD_GRACE_SECONDS)
        self.assertEqual([plans[n]['pause'] for n in 'abc'], [False, False, True])

    def test_later_waiting_workflow_never_pauses_earlier_ones(self):
        workflows = [lease('a', 1, units=3), lease('b', 2, units=0, waiting_bytes=GIB, waiting_since=0)]
        plans = allocate(workflows, 0, 64, 2 * GIB, now=1000)
        self.assertFalse(plans['a']['pause'])
        self.assertFalse(plans['b']['keep_waiting'])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        p = patch.object(lanes, 'snapshot', return_value=dict(available=2 * GIB, cores=8)); p.start(); self.addCleanup(p.stop)

    def job(self, name, number, started):
        directory = self.root / 'tmp' / name
        (directory / 'working').mkdir(parents=True)
        atomic_json(directory / 'job.json', {'id': name, 'workflow_no': number, 'started_at': started, 'status': 'RUNNING'})
        return directory

    def test_lease_lifecycle_report_and_isolated_ledger(self):
        first = self.job('a', 1, '2026-10-04T00:00:00+00:00')
        with lanes.Lease(first) as held:
            self.assertTrue((self.root / 'config' / 'lanes.json').exists())
            held.stage('tts')
            self.assertGreaterEqual(lanes.report(first, 'tts', 2, GIB, 0, 4)['target'], 4)
            self.assertFalse(lanes.others_running(first))
        self.assertEqual(read_json(self.root / 'config' / 'lanes.json')['leases'], {})

    def test_stale_lease_expires(self):
        first = self.job('a', 1, '2026-10-04T00:00:00+00:00')
        atomic_json(self.root / 'config' / 'lanes.json', {'leases': {'dead': lease('dead', 0, heartbeat=time.time() - 60)}})
        self.assertFalse(lanes.others_running(first))

    def test_waiting_and_auto_pause_mark_the_job(self):
        first = self.job('a', 1, '2026-10-04T00:00:00+00:00')
        second = self.job('b', 2, '2026-10-04T00:01:00+00:00')
        with lanes.Lease(first), lanes.Lease(second):
            lanes.report(second, 'tts', 2, GIB, 0, 4)
            self.assertTrue(lanes.waiting(first, GIB))
            self.assertTrue(lanes.others_running(first))
            lanes.auto_pause(second, 'a')
        job = read_json(second / 'job.json')
        self.assertEqual(job['auto_paused_for'], 'a')
        self.assertIn('#000001', job['memory_pause_reason'])
        self.assertEqual(read_json(second / 'working' / 'cancel.signal')['mode'], 'pause')


if __name__ == '__main__':
    unittest.main()


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'config'
        for target in (patch.object(lanes, 'config_dir', return_value=self.config),
                       patch.object(lanes, 'snapshot', return_value=dict(available=3 * GIB, cores=8))):
            target.start(); self.addCleanup(target.stop)

    def leases(self, *items):
        atomic_json(self.config / 'lanes.json', {'leases': {item['id']: {**item, 'heartbeat': time.time()} for item in items}})

    def test_first_workflow_starts_when_nothing_runs(self):
        start, resume, _ = lanes.admission([{'id': 'a', 'status': 'QUEUED', '_next_stage': 'download'}])
        self.assertEqual((start['id'], resume), ('a', None))

    def test_new_workflow_starts_beside_a_running_one_when_its_stage_fits(self):
        self.leases(lease('run', 1, demand=2, units=2, unit=GIB // 2))
        start, _, _ = lanes.admission([{'id': 'b', 'status': 'QUEUED', '_next_stage': 'download'}])
        self.assertEqual(start['id'], 'b')
        start, _, _ = lanes.admission([{'id': 'c', 'status': 'QUEUED', '_next_stage': 'transcription'}])
        self.assertIsNone(start)  # 5.2 GiB ASR does not fit beside it on this budget

    def test_waiting_workflow_blocks_new_admission(self):
        self.leases(lease('run', 1, waiting_bytes=GIB, waiting_since=time.time()))
        self.assertEqual(lanes.admission([{'id': 'b', 'status': 'QUEUED', '_next_stage': 'download'}])[:2], (None, None))

    def test_auto_paused_workflow_resumes_after_cooldown_only(self):
        job = {'id': 'p', 'status': 'PAUSED', '_next_stage': 'tts', 'auto_paused_at': time.time()}
        self.assertEqual(lanes.admission([job])[:2], (None, None))
        job['auto_paused_at'] = time.time() - lanes.RESUME_COOLDOWN_SECONDS - 1
        self.assertEqual(lanes.admission([job])[1]['id'], 'p')

    def test_workflow_that_yielded_waits_until_that_workflow_finishes(self):
        self.leases(lease('first', 1, demand=0, units=0))
        job = {'id': 'p', 'status': 'PAUSED', '_next_stage': 'download', 'auto_paused_for': 'first',
               'auto_paused_at': time.time() - lanes.RESUME_COOLDOWN_SECONDS - 1}
        self.assertEqual(lanes.admission([job])[:2], (None, None))
        self.leases()
        self.assertEqual(lanes.admission([job])[1]['id'], 'p')

    def test_user_paused_workflow_is_never_resumed_by_the_scheduler(self):
        from audio_translate.workflow import scheduling
        root = Path(self.temp.name) / 'tmp' / 'u'; (root / 'working').mkdir(parents=True)
        atomic_json(root / 'job.json', {'id': 'u', 'status': 'PAUSED', 'steps': {}})
        with patch.object(scheduling.results, 'workspace', return_value=root), \
             patch('audio_translate.workflow.manage.resume') as resume:
            self.assertEqual(scheduling.admit(['u'])['resumed'], None)
        resume.assert_not_called()
