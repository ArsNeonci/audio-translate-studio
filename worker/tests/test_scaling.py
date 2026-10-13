import unittest

from audio_translate.core.scaling import GainTrial


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class GainTrialTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(); self.gain = GainTrial(window=30, retry=600, clock=self.clock)

    def run_for(self, seconds, chars_per_second):
        for _ in range(int(seconds)):
            self.clock.now += 1; self.gain.record(chars_per_second)

    def test_needs_a_steady_measured_baseline_before_trying(self):
        self.gain.observe(1)
        self.assertFalse(self.gain.can_try(1))
        self.run_for(30, 10)
        self.assertTrue(self.gain.can_try(1))

    def test_any_increase_keeps_the_unit(self):
        self.gain.observe(1); self.run_for(30, 10)
        self.gain.begin(1); self.run_for(30, 10.5)
        self.assertEqual(self.gain.verdict(), 'keep')
        self.assertEqual(self.gain.state()['blocked'], [])

    def test_no_increase_reverts_and_blocks_that_level_until_retry(self):
        self.gain.observe(1); self.run_for(30, 10)
        self.gain.begin(1); self.run_for(15, 10)
        self.assertIsNone(self.gain.verdict())  # still measuring
        self.run_for(15, 9)
        self.assertEqual(self.gain.verdict(), 'revert')
        self.gain.observe(1); self.run_for(30, 10)
        self.assertFalse(self.gain.can_try(1))
        self.clock.now += 600
        self.run_for(30, 10)
        self.assertTrue(self.gain.can_try(1))

    def test_pressure_shrink_cancels_a_trial(self):
        self.gain.observe(2); self.run_for(30, 10)
        self.gain.begin(2); self.gain.observe(2)
        self.assertIsNone(self.gain.trial)


if __name__ == '__main__':
    unittest.main()
