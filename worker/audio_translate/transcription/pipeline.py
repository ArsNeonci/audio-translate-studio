"""Bounded-memory YouTube Chinese transcription worker.

FunASR is installed from worker/requirements.txt in the application environment.
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
    from audio_translate.core.storage import atomic_json as durable_json
    durable_json(path, value)


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
    from audio_translate.core.license_gate import assert_allowed
    assert_allowed(False)
    path = job_dir / "job.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    job.update(changes)
    from audio_translate.core.control import check_cancel
    check_cancel(job_dir)
    if job.get('workflow_version') == 2 and 'progress' in changes:
        from audio_translate.core.storage import progress as stage_progress
        stage = 'download' if changes.get('status',job.get('status')) == 'DOWNLOADING' else 'transcription'
        changes.pop('progress',None)
        job.update(changes)
        atomic_json(path,job)
        if stage == 'transcription':
            status = changes.get('status',job.get('status'))
            if status == 'VAD' or status == 'MERGING':
                stage_progress(job_dir,stage,status,0,None)
            elif status == 'TRANSCRIPTION_COMPLETED': stage_progress(job_dir,stage,status,1,1)
            else: stage_progress(job_dir,stage,status,changes.get('processed_ms',job.get('processed_ms',0)),job.get('duration_ms'))
        return job
    atomic_json(path, job)
    return job


def source_file(job_dir):
    candidates = [p for p in (job_dir / "source").glob("audio.*")
                  if p.is_file() and ".part" not in p.name and not p.name.endswith((".ytdl", ".tmp"))]
    return candidates[0] if candidates else None


def validate_cookie_file(path):
    """Reject malformed exports before yt-dlp can echo cookie values in warnings."""
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except UnicodeError:
        raise ValueError("File cookie phải dùng UTF-8 và định dạng Netscape cookies.txt.") from None
    error = "File cookie không đúng định dạng Netscape cookies.txt. Hãy xuất lại cookie YouTube; không dán chuỗi Cookie từ trình duyệt."
    if not lines or not re.match(r"^#(?: Netscape)? HTTP Cookie File", lines[0]):
        raise ValueError(error)
    count = 0
    for line in lines[1:]:
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if (len(fields) != 7 or fields[1] not in ("TRUE", "FALSE")
                or fields[3] not in ("TRUE", "FALSE")
                or fields[4] and not fields[4].isdigit()):
            raise ValueError(error)
        count += 1
    if not count:
        raise ValueError("File cookie chưa chứa cookie nào. Hãy xuất lại cookie YouTube.")


def download(job_dir):
    existing = source_file(job_dir)
    if existing:
        return existing
    from audio_translate.core.storage import read_json
    saved = read_json(job_dir / "job.json")
    if saved.get("source_upload"):
        raise ValueError("File audio đã tải lên không còn trong workflow này. Hãy tạo workflow mới và chọn lại file.")
    if not saved.get("url"):
        raise ValueError("Workflow này không có link YouTube.")
    # The yt-dlp release and the order of YouTube clients come from the gateway when one has been published (signed, see
    # ytdlp_update); otherwise the bundled yt-dlp and the built-in order are used. This must happen before yt_dlp is imported.
    from audio_translate.transcription import ytdlp_update
    ytdlp_update.refresh()
    version = ytdlp_update.activate()
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    job = update(job_dir, status="DOWNLOADING", progress=1, error=None)
    from audio_translate.core.storage import progress
    progress(job_dir,"download","DOWNLOADING",0,None)
    last_progress = -1

    def hook(state):
        nonlocal last_progress
        if state.get("status") != "downloading":
            return
        from audio_translate.core.control import check_cancel
        from audio_translate.core.storage import progress
        check_cancel(job_dir)
        total = state.get("total_bytes")
        downloaded = state.get("downloaded_bytes", 0)
        pct = round(downloaded * 100 / total,2) if total else None
        if pct != last_progress:
            last_progress = pct
            progress(job_dir,"download","DOWNLOADING",downloaded,total)

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
        "no_warnings": False,
    }
    from audio_translate.transcription.youtube_session import cookies_for_download

    def fetch(client=None, profile_cookies=None, cookies_file=None):
        chosen = dict(options)
        if client:
            chosen["extractor_args"] = {"youtube": {"player_client": [client]}}
        if cookies_file:
            if not Path(cookies_file).is_file():
                raise FileNotFoundError(f"Không tìm thấy YTDLP_COOKIES_FILE: {cookies_file}")
            validate_cookie_file(cookies_file)
            chosen["cookiefile"] = cookies_file
        with YoutubeDL(chosen) as ydl:
            if profile_cookies is not None:
                for cookie in profile_cookies:
                    ydl.cookiejar.set_cookie(cookie)
            return ydl.extract_info(job["url"], download=True)

    info, attempts = try_attempts(job_dir, ytdlp_update.attempts(), fetch, DownloadError, cookies_for_download)
    write_attempts(job_dir, attempts, version)
    if info is None:
        # Every way failed. Ask the gateway now (at most every 15 minutes) whether a newer yt-dlp or client order exists:
        # it is installed for the next attempt, since yt_dlp is already loaded in this process.
        result = ytdlp_update.refresh(force=True)
        error = refused(attempts)
        if result.get("changed"):
            error = RuntimeError(f"{error} Đã nhận bản cập nhật bộ tải YouTube; bấm Thử lại.")
        raise error
    if info.get("vcodec") not in (None, "none"):
        raise RuntimeError("YouTube không cung cấp audio-only stream cho URL này.")
    path = source_file(job_dir)
    if not path:
        raise RuntimeError("yt-dlp không tạo được file audio.")
    update(job_dir, name=info.get("title") or job["name"], duration_ms=int((info.get("duration") or 0) * 1000), progress=10)
    progress(job_dir,"download","DOWNLOADING",1,1)
    return path


# Errors that another YouTube client cannot fix: stop trying, and do not spend more requests (429 makes it worse).
FINAL_ERRORS = ("http error 429", "private video", "has been removed", "members-only", "members only",
                "live event will begin", "premieres in", "copyright")


def try_attempts(job_dir, plan, fetch, error_type, load_cookies):
    """Run the attempts in order until one returns info. Returns (info or None, [(attempt, used cookies kind, error text or None)]).
    The saved sign-in is read only when an attempt needs it; attempts that need cookies are skipped when there are none."""
    attempts, cookies, loaded = [], (None, None), False
    for step in plan:
        if step.get("cookies"):
            if not loaded:
                profile = load_cookies()
                cookies, loaded = (profile, None if profile is not None else os.getenv("YTDLP_COOKIES_FILE") or None), True
            if cookies == (None, None):
                continue
        if attempts:
            # A partial file from a failed attempt may belong to another format; never resume into it.
            for leftover in (job_dir / "source").glob("audio.*"):
                if leftover.name.endswith((".part", ".ytdl")) or ".part-" in leftover.name:
                    leftover.unlink(missing_ok=True)
        kind = None if not step.get("cookies") else ("profile" if cookies[0] is not None else "file")
        try:
            info = fetch(step.get("client"), *(cookies if step.get("cookies") else (None, None)))
            attempts.append((step, kind, None))
            if info: return info, attempts
        except error_type as exc:
            attempts.append((step, kind, str(exc)))
            if any(marker in str(exc).lower() for marker in FINAL_ERRORS):
                break
    return None, attempts


def write_attempts(job_dir, attempts, version):
    """What was tried, for support: client, whether a sign-in was used, and the first part of the error. No cookie values."""
    from audio_translate.core.storage import atomic_json
    rows = [{"client": step.get("client") or "default", "cookies": kind, "ok": error is None, "error": (error or "")[-300:] or None}
            for step, kind, error in attempts]
    (job_dir / "working").mkdir(exist_ok=True)
    atomic_json(job_dir / "working" / "download-attempts.json", {"yt_dlp": version or "bundled", "attempts": rows})


def refused(attempts):
    """The one error the owner sees after every attempt failed, chosen from what YouTube said."""
    errors = [(kind, error) for _, kind, error in attempts if error]
    if not attempts:
        return RuntimeError("YouTube yêu cầu xác thực. Mở Settings → Kết nối YouTube rồi đăng nhập.")
    if not errors:
        return RuntimeError("yt-dlp không trả về thông tin video.")
    texts = [error.lower() for _, error in errors]
    if any("http error 429" in text for text in texts):
        return RuntimeError("YouTube giới hạn số lượt truy cập (HTTP 429). Hãy chờ trước khi thử lại; kiểm tra VPN/proxy hoặc thử mạng khác nếu lỗi kéo dài.")
    with_cookies = [(kind, error) for kind, error in errors if kind]
    if not with_cookies and any("sign in to confirm" in text for text in texts):
        # Only anonymous attempts ran: there is no saved sign-in to use.
        return RuntimeError("YouTube yêu cầu xác thực. Mở Settings → Kết nối YouTube rồi đăng nhập. Hoặc chọn \"Tệp âm thanh tiếng Trung\" và nạp file audio.")
    if with_cookies:
        kind, error = with_cookies[-1]
        text = error.lower()
        if "sign in to confirm" in text:
            if kind == "profile":
                from audio_translate.transcription.youtube_session import mark_auth_required
                mark_auth_required()
                return RuntimeError("YouTube yêu cầu xác thực lại. Mở Settings → Kết nối YouTube, đăng nhập trong profile riêng rồi Retry DOWNLOAD. Không cần xuất cookie hoặc đóng gói lại app.")
            return RuntimeError("YouTube vẫn yêu cầu xác thực dù đã dùng cookie. Hãy xuất lại cookie YouTube từ phiên trình duyệt xem được video, cập nhật file rồi bấm Thử lại.")
        if "needs to be reloaded" in text:
            return RuntimeError("YouTube từ chối phiên đăng nhập đã lưu (\"The page needs to be reloaded\"). Mở Settings → Kết nối YouTube, đăng nhập lại rồi bấm Thử lại.")
    return RuntimeError(f"Không tải được audio YouTube: {errors[-1][1]}")


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
    model = AutoModel(model=model_reference("fsmn-vad"), device="cpu",
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
                from audio_translate.core.control import check_cancel
                check_cancel(job_dir)
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
                    from audio_translate.transcription.transcription_progress import report
                    report(job_dir, 1, processed_ms, total_ms)
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
    for index, (start, end) in enumerate(spans):
        from audio_translate.core.control import check_cancel
        from audio_translate.transcription.transcription_progress import report
        check_cancel(job_dir)
        report(job_dir, 2, index, max(1, len(spans)) * 2)
        if groups and start - groups[-1][1] <= 700 and end - groups[-1][0] <= MAX_CHUNK_MS:
            groups[-1][1] = max(end, groups[-1][1])
        else:
            groups.append([start, end])
    chunks = []
    for i, (start, end) in enumerate(groups):
        from audio_translate.core.control import check_cancel
        from audio_translate.transcription.transcription_progress import report
        check_cancel(job_dir)
        report(job_dir, 2, len(groups) + i, max(1, len(groups)) * 2)
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
    # First run: fetch the speech models here (progress shown, resumable, no start-up deadline) so the workers never time out while downloading.
    if any(not (job_dir / "working" / f"chunk-{index:06d}.json").exists() for index in range(len(chunks))):
        from audio_translate.transcription.model_prefetch import ensure_models
        ensure_models(job_dir)
    if os.getenv('FUNASR_DEVICE', 'cpu') == 'cpu':
        from audio_translate.transcription.asr_runtime import run
        return run(job_dir, source, chunks)
    return transcribe_serial(job_dir, source, chunks)


def transcribe_serial(job_dir, source, chunks):
    from funasr import AutoModel

    update(job_dir, status="TRANSCRIBING", progress=0, processed_ms=0, chunks_total=len(chunks))
    if not chunks:
        return
    if all((job_dir / "working" / f"chunk-{index:06d}.json").exists() for index in range(len(chunks))):
        update(job_dir, progress=100, processed_ms=read_json_duration(job_dir), chunks_done=len(chunks))
        return
    model = AutoModel(model=model_reference("paraformer-zh"),
                      ncpu=max(1, int(os.getenv('AI_NUM_THREADS', '4'))),
                      vad_model=model_reference("fsmn-vad"), punc_model=model_reference("ct-punc"),
                      vad_kwargs={"max_single_segment_time": MAX_CHUNK_MS},
                      device=os.getenv("FUNASR_DEVICE", "cpu"), disable_update=True,
                      disable_pbar=True, trust_remote_code=False)
    process = decoder(source)
    cursor = 0
    tail = b""
    try:
        for index, chunk in enumerate(chunks):
            from audio_translate.core.control import check_cancel
            check_cancel(job_dir)
            path = job_dir / "working" / f"chunk-{index:06d}.json"
            audio, cursor, tail = audio_piece(process.stdout, cursor, tail, chunk["start"], chunk["end"])
            if path.exists():
                from audio_translate.transcription.transcription_progress import report
                report(job_dir, 3, index + 1, len(chunks))
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
            from audio_translate.transcription.transcription_progress import report
            report(job_dir, 3, index + 1, len(chunks))
            update(job_dir, progress=30 + int(65 * (index + 1) / len(chunks)), chunks_done=index + 1, processed_ms=chunk["own_end"])
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
        total_rows = 0
        for index in range(len(chunks)):
            rows = json.loads((job_dir / "working" / f"chunk-{index:06d}.json").read_text(encoding="utf-8"))
            total_rows += len(rows)
            ordered_chunks.append(iter(rows))
        for visited, row in enumerate(heapq.merge(*ordered_chunks, key=lambda item: (item["start_ms"], item["end_ms"]))):
            from audio_translate.core.control import check_cancel
            from audio_translate.transcription.transcription_progress import report
            check_cancel(job_dir)
            report(job_dir, 4, visited + 1, total_rows)
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
    from audio_translate.core.control import check_cancel
    check_cancel(job_dir)
    os.replace(jsonl_tmp, job_dir / "transcript.jsonl")
    os.replace(md_tmp, job_dir / "transcript.zh.md")
    # Keep the legacy alias for existing consumers, and publish the canonical name.
    import shutil
    zh_temp = job_dir / "transcript.zh.jsonl.tmp"
    shutil.copyfile(job_dir / "transcript.jsonl", zh_temp)
    os.replace(zh_temp, job_dir / "transcript.zh.jsonl")
    update(job_dir, status="TRANSCRIPTION_COMPLETED", progress=100, rows=rows_written, error=None)


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


def read_json_duration(job_dir):
    return json.loads((job_dir/"job.json").read_text(encoding="utf-8")).get("duration_ms",0)
