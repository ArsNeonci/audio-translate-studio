"""Bounded-memory YouTube Chinese transcription worker.

The local FunASR checkout can be used with PYTHONPATH, or install FunASR with pip.
"""

import argparse
from contextlib import contextmanager
import heapq
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

RATE = 16000
FRAME_MS = 200
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2
MAX_CHUNK_MS = 30000
OVERLAP_MS = 2500


class JobBusy(Exception):
    pass


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


@contextmanager
def job_lock(job_dir):
    """Prevent two Next.js processes from writing one job concurrently."""
    lock_path = job_dir / "working" / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise JobBusy()
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update(job_dir, **changes):
    path = job_dir / "job.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    job.update(changes)
    atomic_json(path, job)
    return job


def source_file(job_dir):
    candidates = [p for p in (job_dir / "source").glob("audio.*")
                  if p.is_file() and ".part" not in p.name and not p.name.endswith(".ytdl")]
    return candidates[0] if candidates else None


def download(job_dir):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    existing = source_file(job_dir)
    if existing:
        return existing
    job = update(job_dir, status="DOWNLOADING", progress=1, error=None)
    last_progress = -1

    def hook(state):
        nonlocal last_progress
        if state.get("status") != "downloading":
            return
        total = state.get("total_bytes") or state.get("total_bytes_estimate")
        downloaded = state.get("downloaded_bytes", 0)
        pct = int(downloaded * 10 / total) if total else 1
        if pct != last_progress:
            last_progress = pct
            update(job_dir, progress=min(10, max(1, pct)))

    options = {
        "format": "bestaudio",
        "js_runtimes": {"node": {}},
        "outtmpl": str(job_dir / "source" / "audio.%(ext)s"),
        "noplaylist": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
    }
    cookies_file = os.getenv("YTDLP_COOKIES_FILE")
    if cookies_file:
        if not Path(cookies_file).is_file():
            raise FileNotFoundError(f"Không tìm thấy YTDLP_COOKIES_FILE: {cookies_file}")
        options["cookiefile"] = cookies_file
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(job["url"], download=True)
    except DownloadError as exc:
        detail = str(exc)
        if "Sign in to confirm" in detail or "HTTP Error 429" in detail:
            raise RuntimeError("YouTube yêu cầu xác thực hoặc đang giới hạn truy cập từ mạng này. Hãy cấu hình YTDLP_COOKIES_FILE và thử lại.") from exc
        raise RuntimeError(f"Không tải được audio YouTube: {detail}") from exc
    if not info or info.get("vcodec") not in (None, "none"):
        raise RuntimeError("YouTube không cung cấp audio-only stream cho URL này.")
    path = source_file(job_dir)
    if not path:
        raise RuntimeError("yt-dlp không tạo được file audio.")
    update(job_dir, name=info.get("title") or job["name"], duration_ms=int((info.get("duration") or 0) * 1000), progress=10)
    return path


def duration_ms(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return int(float(result.stdout.strip()) * 1000)


def model_reference(alias):
    """Use FunASR's official alias map and an already complete local snapshot."""
    cache = os.getenv("MODELSCOPE_CACHE")
    if cache:
        from funasr.download.name_maps_from_hub import name_maps_ms

        model_id = name_maps_ms[alias]
        snapshot = Path(cache) / "models" / model_id.replace("/", "--") / "snapshots" / "master"
        if (snapshot / "config.yaml").is_file() and (snapshot / "model.pt").is_file():
            return str(snapshot)
    return alias


def decoder(path):
    return subprocess.Popen(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )


def exact_read(stream, length):
    parts = []
    remaining = length
    while remaining:
        block = stream.read(remaining)
        if not block:
            break
        parts.append(block)
        remaining -= len(block)
    return b"".join(parts)


def vad_pass(job_dir, source, total_ms):
    from funasr import AutoModel

    spans_path = job_dir / "working" / "vad.jsonl"
    if spans_path.exists() and (job_dir / "working" / "vad.done").exists():
        return
    update(job_dir, status="VAD", progress=11)
    model = AutoModel(model=model_reference("fsmn-vad"), device=os.getenv("FUNASR_DEVICE", "cpu"),
                      disable_update=True, disable_pbar=True,
                      max_single_segment_time=MAX_CHUNK_MS)
    cache = {}
    process = decoder(source)
    pending_start = None
    consumed = 0
    last_progress = -1
    try:
        with spans_path.open("w", encoding="utf-8") as out:
            data = exact_read(process.stdout, FRAME_BYTES)
            while data:
                next_data = exact_read(process.stdout, FRAME_BYTES)
                consumed += len(data) // 2
                final = not next_data
                samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
                result = model.generate(input=samples, fs=RATE, cache=cache,
                                        is_final=final, chunk_size=FRAME_MS)
                for start, end in result[0].get("value", []):
                    if start >= 0:
                        pending_start = start
                    if end >= 0:
                        begin = pending_start if pending_start is not None else max(0, end - MAX_CHUNK_MS)
                        if end > begin:
                            out.write(json.dumps([begin, end]) + "\n")
                        pending_start = None
                processed_ms = consumed * 1000 // RATE
                pct = 11 + round(19 * min(1, processed_ms / max(1, total_ms)), 2)
                if pct != last_progress:
                    last_progress = pct
                    update(job_dir, progress=pct, processed_ms=processed_ms)
                data = next_data
            if pending_start is not None:
                out.write(json.dumps([pending_start, consumed * 1000 // RATE]) + "\n")
        if process.wait() != 0:
            raise RuntimeError("FFmpeg không decode được audio để chạy VAD.")
        (job_dir / "working" / "vad.done").write_text("ok", encoding="ascii")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def make_chunks(job_dir):
    path = job_dir / "working" / "chunks.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    spans = []
    with (job_dir / "working" / "vad.jsonl").open(encoding="utf-8") as vad_file:
        for line in vad_file:
            start, end = json.loads(line)
            if end > start:
                spans.append((start, end))
    spans.sort()
    groups = []
    for start, end in spans:
        if groups and start - groups[-1][1] <= 700 and end - groups[-1][0] <= MAX_CHUNK_MS:
            groups[-1][1] = max(end, groups[-1][1])
        else:
            groups.append([start, end])
    chunks = []
    for i, (start, end) in enumerate(groups):
        before = groups[i - 1][1] if i else -100000
        after = groups[i + 1][0] if i + 1 < len(groups) else 10**15
        chunks.append({
            "start": max(0, start - (OVERLAP_MS if start - before <= 100 else 0)),
            "end": end + (OVERLAP_MS if after - end <= 100 else 0),
            "own_start": start,
            "own_end": end,
        })
    atomic_json(path, chunks)
    return chunks


def audio_piece(stream, cursor, tail, start_ms, end_ms):
    start_sample = start_ms * RATE // 1000
    end_sample = end_ms * RATE // 1000
    prefix = b""
    if start_sample < cursor:
        overlap = cursor - start_sample
        if overlap * 2 > len(tail):
            raise RuntimeError("Overlap vượt quá bộ đệm audio.")
        prefix = tail[-overlap * 2:]
    skip = max(0, start_sample - cursor)
    while skip:
        block = stream.read(min(skip * 2, 1024 * 1024))
        if not block:
            raise RuntimeError("Audio kết thúc trước đoạn VAD dự kiến.")
        count = len(block) // 2
        cursor += count
        skip -= count
    length = max(0, end_sample - cursor)
    data = exact_read(stream, length * 2)
    cursor += len(data) // 2
    combined = prefix + data
    return np.frombuffer(combined, dtype="<i2").astype(np.float32) / 32768.0, cursor, combined[-RATE * 6 * 2:]


def clean_text(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def transcribe(job_dir, source, chunks):
    from funasr import AutoModel

    update(job_dir, status="TRANSCRIBING", progress=30, chunks_total=len(chunks))
    if not chunks:
        return
    if all((job_dir / "working" / f"chunk-{index:06d}.json").exists() for index in range(len(chunks))):
        update(job_dir, progress=95, chunks_done=len(chunks))
        return
    model = AutoModel(model=model_reference("paraformer-zh"),
                      vad_model=model_reference("fsmn-vad"), punc_model=model_reference("ct-punc"),
                      vad_kwargs={"max_single_segment_time": MAX_CHUNK_MS},
                      device=os.getenv("FUNASR_DEVICE", "cpu"), disable_update=True,
                      disable_pbar=True, trust_remote_code=False)
    process = decoder(source)
    cursor = 0
    tail = b""
    try:
        for index, chunk in enumerate(chunks):
            path = job_dir / "working" / f"chunk-{index:06d}.json"
            audio, cursor, tail = audio_piece(process.stdout, cursor, tail, chunk["start"], chunk["end"])
            if path.exists():
                continue
            if not len(audio):
                raise RuntimeError(f"Đoạn audio {index} trống.")
            result = model.generate(input=audio, fs=RATE, batch_size_s=30,
                                    batch_size_threshold_s=30, sentence_timestamp=True)
            item = result[0] if result else {}
            sentences = item.get("sentence_info") or []
            if not sentences and clean_text(item.get("text", "")):
                stamps = item.get("timestamp") or []
                sentences = [{"start": stamps[0][0] if stamps else 0,
                              "end": stamps[-1][1] if stamps else len(audio) * 1000 // RATE,
                              "text": item["text"]}]
            rows = []
            for sentence in sentences:
                text = clean_text(sentence.get("text", ""))
                if not text:
                    continue
                start = chunk["start"] + int(sentence["start"])
                end = chunk["start"] + int(sentence["end"])
                midpoint = (start + end) / 2
                if chunk["own_start"] <= midpoint < chunk["own_end"] + (index == len(chunks) - 1):
                    rows.append({"start_ms": max(0, start), "end_ms": max(start, end), "text": text})
            rows.sort(key=lambda row: (row["start_ms"], row["end_ms"]))
            atomic_json(path, rows)
            update(job_dir, progress=30 + int(65 * (index + 1) / len(chunks)), chunks_done=index + 1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def merge(job_dir, chunks):
    update(job_dir, status="MERGING", progress=96)
    jsonl_tmp = job_dir / "transcript.jsonl.tmp"
    md_tmp = job_dir / "transcript.zh.md.tmp"
    previous_end = -1
    previous_start = -1
    paragraph = []
    paragraph_start = None
    rows_written = 0
    with jsonl_tmp.open("w", encoding="utf-8", newline="\n") as canonical, md_tmp.open("w", encoding="utf-8", newline="\n") as markdown:
        ordered_chunks = []
        for index in range(len(chunks)):
            rows = json.loads((job_dir / "working" / f"chunk-{index:06d}.json").read_text(encoding="utf-8"))
            ordered_chunks.append(iter(rows))
        for row in heapq.merge(*ordered_chunks, key=lambda item: (item["start_ms"], item["end_ms"])):
            start, end = row["start_ms"], row["end_ms"]
            shared_ms = max(0, min(previous_end, end) - max(previous_start, start))
            if previous_end > 0 and (end <= previous_end and start < previous_end - 500 or
                                     shared_ms > 0.65 * max(1, min(end - start, previous_end - previous_start))):
                continue  # timestamp overlap at a forced boundary
            if paragraph and (start - previous_end > 1500 or start - paragraph_start > 60000 or len("".join(paragraph)) > 240):
                markdown.write("".join(paragraph) + "\n\n")
                paragraph = []
            if not paragraph:
                paragraph_start = start
            paragraph.append(row["text"])
            canonical.write(json.dumps(row, ensure_ascii=False) + "\n")
            previous_start, previous_end = start, max(previous_end, end)
            rows_written += 1
        if paragraph:
            markdown.write("".join(paragraph) + "\n")
    os.replace(jsonl_tmp, job_dir / "transcript.jsonl")
    os.replace(md_tmp, job_dir / "transcript.zh.md")
    update(job_dir, status="COMPLETED", progress=100, rows=rows_written, error=None)


def run(job_dir):
    (job_dir / "source").mkdir(parents=True, exist_ok=True)
    (job_dir / "working").mkdir(parents=True, exist_ok=True)
    source = download(job_dir)
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    total = job.get("duration_ms") or duration_ms(source)
    update(job_dir, duration_ms=total)
    vad_pass(job_dir, source, total)
    chunks = make_chunks(job_dir)
    transcribe(job_dir, source, chunks)
    merge(job_dir, chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    args = parser.parse_args()
    try:
        with job_lock(args.job_dir):
            run(args.job_dir)
    except JobBusy:
        sys.exit(0)
    except Exception as exc:
        update(args.job_dir, status="FAILED", error=f"{type(exc).__name__}: {exc}")
        print(f"Worker failed: {exc}", file=sys.stderr)
        raise
