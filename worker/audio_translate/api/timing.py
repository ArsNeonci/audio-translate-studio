"""A small timing log: how long the steps of one Convert click took, so a slow start can be pinned to a step instead of guessed.

`timing.jsonl` in the data folder gets one line per click: the milliseconds after the request arrived at which each step finished
(licence check, storage ready, the worker that checks the machine and creates the run), plus what the worker measured inside itself.
A click that takes 2 seconds or more is marked "slow". The file is capped (the older half is dropped); it holds no personal data."""
import json
import time

from audio_translate.core.storage import DATA

LIMIT = 256 * 1024
SLOW_MS = 2000


class Stopwatch:
    def __init__(self):
        self.start = time.monotonic()
        self.marks = {}

    def mark(self, name):
        self.marks[name] = round((time.monotonic() - self.start) * 1000)

    def total(self):
        return round((time.monotonic() - self.start) * 1000)


def log(route, watch, inside=None, outcome=None):
    """Appends one line; never raises (a log must not break a click)."""
    try:
        path = DATA / 'timing.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        total = watch.total()
        line = {'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'route': route, 'total_ms': total, 'steps_ms': watch.marks, 'worker_ms': inside or {}, 'outcome': outcome}
        if total >= SLOW_MS: line['slow'] = True
        if path.exists() and path.stat().st_size > LIMIT:
            rows = path.read_text(encoding='utf-8').splitlines()
            path.write_text('\n'.join(rows[len(rows) // 2:]) + '\n', encoding='utf-8')
        with path.open('a', encoding='utf-8') as out:
            out.write(json.dumps(line, ensure_ascii=False) + '\n')
    except Exception:
        pass
