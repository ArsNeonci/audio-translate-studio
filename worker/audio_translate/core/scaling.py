"""Grow parallel units one at a time and keep each only if it is actually faster.

Used by Translation slots and TTS workers (ASR keeps its own equivalent window in
transcription/asr_runtime.py). The caller adds one unit after `scale_up_seconds`
of healthy resources; this class decides whether that is allowed and judges the
trial by measured throughput (source characters per second). There is no
minimum gain: any increase keeps the unit, otherwise it is removed and that
level is not retried for `retry_seconds`.
"""
from collections import deque
from time import monotonic


class GainTrial:
    def __init__(self, window=30.0, retry=600.0, clock=monotonic):
        self.window, self.retry, self.clock = float(window), float(retry), clock
        self.events = deque()
        self.level = None
        self.level_since = None
        self.trial = None
        self.blocked = {}

    def record(self, amount):
        now = self.clock()
        self.events.append((now, float(amount)))
        while self.events and self.events[0][0] < now - 4 * self.window:
            self.events.popleft()

    def rate(self, since, until=None):
        until = self.clock() if until is None else until
        if until <= since:
            return 0.0
        return sum(amount for at, amount in self.events if since <= at <= until) / (until - since)

    def observe(self, count):
        """Track the current unit count; a pressure shrink cancels a running trial."""
        now = self.clock()
        if count != self.level:
            if self.trial and count < self.trial['before'] + 1:
                self.trial = None
            self.level, self.level_since = count, now

    def can_try(self, count):
        """True when count+1 may be tried: steady measured baseline and not blocked."""
        now = self.clock()
        return (self.trial is None and self.level == count and self.level_since is not None
                and now - self.level_since >= self.window and self.rate(now - self.window, now) > 0
                and self.blocked.get(count + 1, 0) <= now)

    def begin(self, before):
        now = self.clock()
        self.trial = dict(before=before, baseline=self.rate(now - self.window, now), started=now)
        self.level, self.level_since = before + 1, now

    def verdict(self):
        """None while measuring; then 'keep' or 'revert' (and the level is blocked)."""
        if not self.trial:
            return None
        now = self.clock()
        if now - self.trial['started'] < self.window:
            return None
        trial, self.trial = self.trial, None
        faster = self.rate(trial['started'], now) > trial['baseline']
        if not faster:
            self.blocked[trial['before'] + 1] = now + self.retry
        return 'keep' if faster else 'revert'

    def state(self):
        now = self.clock()
        return dict(rate_chars_per_second=round(self.rate(now - self.window, now), 2),
                    trial=dict(before=self.trial['before'], baseline=round(self.trial['baseline'], 2),
                               seconds=round(now - self.trial['started'], 1)) if self.trial else None,
                    blocked=sorted(level for level, until in self.blocked.items() if until > now))
