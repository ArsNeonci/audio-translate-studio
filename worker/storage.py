"""Disk checkpoints and OS locks shared by the worker and the rules API."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("AUDIO_DATA_DIR", str(ROOT / "data"))).resolve()


class LockedError(Exception):
    pass


@contextmanager
def file_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Every caller locks the same byte. The OS releases it after a crash.
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                for attempt in range(4):
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if attempt == 3:
                            raise
                        time.sleep(0.025)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockedError("Resource is locked by another process.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows can briefly deny replacement while a polling reader has the
        # old file open. Keep the complete old file visible and retry the rename.
        for attempt in range(8):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.025 * (attempt + 1))
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def file_digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def rows(path, text_key):
    last_start = -1
    with Path(path).open(encoding="utf-8") as handle:
        for index, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"Empty JSONL row {index} in {Path(path).name}")
            row = json.loads(line)
            start, end = row.get("start_ms"), row.get("end_ms")
            if (type(start) is not int or type(end) is not int or start < last_start
                    or start < 0 or end < start or not isinstance(row.get(text_key), str)):
                raise ValueError(f"Invalid segment {index} in {Path(path).name}")
            last_start = start
            yield index, row


def count_rows(path, text_key):
    return sum(1 for _ in rows(path, text_key))


def update_job(job_dir, **changes):
    job = read_json(Path(job_dir) / "job.json")
    job.update(changes)
    atomic_json(Path(job_dir) / "job.json", job)
    return job


STAGES = ["download", "transcription", "translation", "moderation", "tts"]


def progress(job_dir, stage, status, done, total):
    from license_gate import assert_allowed
    assert_allowed(False)
    job = read_json(Path(job_dir) / "job.json")
    from control import check_cancel
    check_cancel(job_dir)
    stages = job.get("stages", {})
    percent = round(max(0, min(100, 100*done/total)),2) if total else None
    if total == 0 and status.endswith('COMPLETED'): percent = 100
    stages[stage] = {"done":done,"total":total,"percent":percent}
    steps = job.get('steps',{})
    if stage.upper() in steps: steps[stage.upper()]['progress'] = percent
    effective = [s.lower() for s in job.get('tool_steps', [s.upper() for s in STAGES])]
    # Equal stage weight, explicitly displayed in the UI; unknown active work
    # stays indeterminate. No clock-based or model speed estimates.
    values = [100 if steps.get(s.upper(),{}).get('state') == 'COMPLETED' else stages.get(s,{}).get('percent',0) for s in effective]
    overall = None if any(v is None for v in values) else round(sum(values)/len(values),2)
    changes = {'steps':steps} if 'steps' in job else {}
    update_job(job_dir, status=status, stages=stages, progress=overall, error=None, failed_stage=None, **changes)



class Checkpoints:
    def __init__(self, job_dir):
        working = Path(job_dir) / "working"
        working.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(working / "postprocess.sqlite3")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS segments (stage TEXT, idx INTEGER, fingerprint TEXT, output TEXT, PRIMARY KEY(stage, idx))")

    def get(self, stage, index, fingerprint):
        found = self.db.execute("SELECT fingerprint, output FROM segments WHERE stage=? AND idx=?", (stage, index)).fetchone()
        return json.loads(found[1]) if found and found[0] == fingerprint else None

    def put(self, stage, index, fingerprint, output):
        self.db.execute("INSERT OR REPLACE INTO segments VALUES (?, ?, ?, ?)",
                        (stage, index, fingerprint, json.dumps(output, ensure_ascii=False)))
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def done_marker(job_dir, stage):
    return Path(job_dir) / "working" / f"{stage}.done.json"


def completed(job_dir, stage, signature):
    path = done_marker(job_dir, stage)
    if not path.exists():
        return False
    marker = read_json(path)
    return marker["signature"] == signature and all(
        (Path(job_dir) / name).is_file() and file_digest(Path(job_dir) / name) == sha
        for name, sha in marker["outputs"].items())


def finish(job_dir, stage, signature, outputs, count):
    atomic_json(done_marker(job_dir, stage), {"signature": signature, "count": count,
        "outputs": {name: file_digest(Path(job_dir) / name) for name in outputs}})


@contextmanager
def text_outputs(job_dir, jsonl_name, md_name):
    jsonl_path, md_path = Path(job_dir) / jsonl_name, Path(job_dir) / md_name
    jtmp, mtmp = jsonl_path.with_suffix(".jsonl.tmp"), md_path.with_suffix(".md.tmp")
    try:
        with jtmp.open("w", encoding="utf-8", newline="\n") as jout, mtmp.open("w", encoding="utf-8", newline="\n") as mout:
            yield jout, mout
            for handle in (jout, mout):
                handle.flush()
                os.fsync(handle.fileno())
        from control import check_cancel
        check_cancel(job_dir)
        os.replace(jtmp, jsonl_path)
        os.replace(mtmp, md_path)
    finally:
        jtmp.unlink(missing_ok=True)
        mtmp.unlink(missing_ok=True)


def write_row(handles, row, text_key):
    handles[0].write(json.dumps(row, ensure_ascii=False) + "\n")
    handles[1].write(row[text_key] + "\n\n")
