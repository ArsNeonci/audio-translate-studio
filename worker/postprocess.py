"""Streaming translation, snapshot moderation, and resumable WAV synthesis."""
import json
import os
from pathlib import Path

from control import check_cancel, Cancelled
from adapters import TranslationAdapter, TTSAdapter, adapter_settings
from rules import ReplaceEngine, ReplacementRules
from storage import (Checkpoints, atomic_json, completed, count_rows, digest, file_digest,
                     finish, progress, read_json, rows, text_outputs, update_job, write_row)


def stage_complete(job_dir, stage):
    """Check durable outputs before the orchestrator starts any model process."""
    job_dir = Path(job_dir)
    config = adapter_settings(job_dir)
    if stage == "translation":
        source = job_dir / "transcript.zh.jsonl"
        signature = digest([file_digest(source), config["translation"]])
    elif stage == "moderation":
        snapshot = job_dir / "working" / "replacement-rules.snapshot.json"
        source = job_dir / "transcript.vi.jsonl"
        if not snapshot.exists() or not source.exists():
            return False
        signature = digest([file_digest(source), read_json(snapshot), "literal-nfc-leftmost-longest-v1"])
    elif stage == "tts":
        source = job_dir / "transcript.vi.moderated.jsonl"
        if not source.exists():
            return False
        signature = digest([file_digest(source), config["tts"]])
    else:
        return False
    if not completed(job_dir, stage, signature):
        return False
    if stage == 'tts':
        try:
            with (job_dir/'voice'/'voice.manifest.jsonl').open(encoding='utf-8') as manifest:
                for line in manifest:
                    item = json.loads(line)
                    name = f"{item['index']:06d}"
                    if item['file'] != name + '.wav': return False
                    wav = job_dir/'voice'/item['file']
                    meta = read_json(job_dir/'working'/'voice-checkpoints'/f'{name}.json')
                    if meta['sha256'] != file_digest(wav): return False
                    audio_info(wav)
        except (OSError, ValueError, KeyError):
            return False
    return True


def translate(job_dir, adapter=None):
    job_dir = Path(job_dir)
    source = job_dir / "transcript.zh.jsonl"
    config = adapter_settings(job_dir)["translation"]
    signature = digest([file_digest(source), config])
    total = count_rows(source, "text")
    if completed(job_dir, "translation", signature):
        progress(job_dir, "translation", "TRANSLATION_COMPLETED", total, total)
        return
    progress(job_dir, "translation", "TRANSLATING", 0, total)
    adapter = adapter or TranslationAdapter(config)
    names = ["transcript.vi.jsonl", "transcript.vi.md"]
    with Checkpoints(job_dir) as checkpoints, text_outputs(job_dir, *names) as handles:
        batch = []
        def flush():
            if not batch:
                return
            missing = [entry for entry in batch if entry[3] is None]
            if missing:
                translated = adapter.translate([entry[1]["text"] for entry in missing])
                if len(translated) != len(missing):
                    raise RuntimeError("Translation adapter changed the segment count")
                for entry, text in zip(missing, translated, strict=True):
                    if not isinstance(text, str) or (entry[1]["text"].strip() and not text.strip()):
                        raise RuntimeError("Invalid translation output")
                    index, row, key, _ = entry
                    result = {"start_ms": row["start_ms"], "end_ms": row["end_ms"], "text_zh": row["text"], "text_vi": text}
                    checkpoints.put("translation", index, key, result)
                    entry[3] = result
            for index, _, _, result in batch:
                write_row(handles, result, "text_vi")
            progress(job_dir, "translation", "TRANSLATING", batch[-1][0], total)
            batch.clear()
        for index, row in rows(source, "text"):
            check_cancel(job_dir)
            key = digest([row, config])
            batch.append([index, row, key, checkpoints.get("translation", index, key)])
            if len(batch) >= config["batch_size"]:
                flush()
        flush()
    finish(job_dir, "translation", signature, names, total)
    progress(job_dir, "translation", "TRANSLATION_COMPLETED", total, total)


def moderate(job_dir, service=None, after_segment=None):
    job_dir = Path(job_dir)
    source = job_dir / "transcript.vi.jsonl"
    service = service or ReplacementRules()
    total = count_rows(source, "text_vi")
    snapshot_path = job_dir / "working" / "replacement-rules.snapshot.json"
    # Even a resumed job uses the first snapshot, regardless of subsequent CRUD.
    with service.locked():
        try:
            if not snapshot_path.exists():
                atomic_json(snapshot_path, service.read())
            snapshot = read_json(snapshot_path)
            engine = ReplaceEngine(snapshot)
            signature = digest([file_digest(source), snapshot, "literal-nfc-leftmost-longest-v1"])
            if completed(job_dir, "moderation", signature):
                progress(job_dir, "moderation", "MODERATION_COMPLETED", total, total)
                return
            progress(job_dir, "moderation", "MODERATING", 0, total)
            names = ["transcript.vi.moderated.jsonl", "transcript.vi.moderated.md"]
            stats = {"total_segments": total, "modified_segments": 0, "total_replacements": 0,
                     "rules_snapshot_sha256": digest(snapshot), "rules": {r["id"]: 0 for r in snapshot}}
            with Checkpoints(job_dir) as checkpoints, text_outputs(job_dir, *names) as handles:
                for index, row in rows(source, "text_vi"):
                    check_cancel(job_dir)
                    key = digest([row, snapshot, "literal-nfc-leftmost-longest-v1"])
                    cached = checkpoints.get("moderation", index, key)
                    if cached is None:
                        text, counts = engine.apply(row["text_vi"])
                        cached = {"row": {**row, "text_vi_moderated": text}, "counts": counts}
                        checkpoints.put("moderation", index, key, cached)
                    result, counts = cached["row"], cached["counts"]
                    stats["modified_segments"] += int(result["text_vi_moderated"] != row["text_vi"])
                    stats["total_replacements"] += sum(counts.values())
                    for rule_id, count in counts.items():
                        stats["rules"][rule_id] += count
                    write_row(handles, result, "text_vi_moderated")
                    if index % 25 == 0 or index == total:
                        progress(job_dir, "moderation", "MODERATING", index, total)
                    if after_segment:
                        after_segment(index)
            atomic_json(job_dir / "moderation-result.json", stats)
            finish(job_dir, "moderation", signature, [*names, "moderation-result.json"], total)
            progress(job_dir, "moderation", "MODERATION_COMPLETED", total, total)
        except Cancelled:
            raise
        except Exception as exc:
            # Publish FAILED before releasing the lock, even for standalone runs.
            update_job(job_dir, status="FAILED", failed_stage="moderation", error=f"{type(exc).__name__}: {exc}")
            raise


def audio_info(path):
    import soundfile as sf
    info = sf.info(str(path))
    if info.channels != 1 or info.samplerate != 48000 or info.subtype != "PCM_16" or info.frames <= 0:
        raise ValueError("Invalid completed segment WAV")
    return info.frames


def concatenate(job_dir, manifest):
    import soundfile as sf
    total_frames = 0
    with manifest.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            total_frames += audio_info(job_dir / "voice" / row["file"])
    target = job_dir / "voice.vi.wav"
    temp = job_dir / "voice.vi.wav.tmp"
    # RIFF WAV cannot represent 40h of PCM. RF64 is its 64-bit WAV extension.
    fmt = "RF64" if total_frames * 2 + 128 >= 0xFFFFFFFF else "WAV"
    try:
        with sf.SoundFile(str(temp), "w", samplerate=48000, channels=1, subtype="PCM_16", format=fmt) as out:
            with manifest.open(encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    with sf.SoundFile(str(job_dir / "voice" / row["file"])) as source:
                        for block in source.blocks(blocksize=65536, dtype="int16"):
                            check_cancel(job_dir)
                            out.write(block)
        check_cancel(job_dir)
        audio_info(temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def synthesize(job_dir, adapter=None):
    job_dir = Path(job_dir)
    # This is the ONLY text input for TTS. Missing moderation is a hard failure.
    source = job_dir / "transcript.vi.moderated.jsonl"
    config = adapter_settings(job_dir)["tts"]
    signature = digest([file_digest(source), config])
    total = count_rows(source, "text_vi_moderated")
    if stage_complete(job_dir, "tts"):
        progress(job_dir, "tts", "TTS_GENERATING", total, total)
        return
    progress(job_dir, "tts", "TTS_GENERATING", 0, total)
    adapter = adapter or TTSAdapter(config)
    voice = job_dir / "voice"
    voice.mkdir(exist_ok=True)
    checkpoint_dir = job_dir / "working" / "voice-checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    manifest = voice / "voice.manifest.jsonl"
    manifest_tmp = manifest.with_suffix(".jsonl.tmp")
    try:
        with manifest_tmp.open("w", encoding="utf-8", newline="\n") as out:
            for index, row in rows(source, "text_vi_moderated"):
                check_cancel(job_dir)
                key = digest([row, config])
                wav = voice / f"{index:06d}.wav"
                meta = checkpoint_dir / f"{index:06d}.json"
                saved = read_json(meta) if meta.exists() else None
                reusable = saved and saved["fingerprint"] == key and wav.exists() and saved["sha256"] == file_digest(wav)
                if not reusable:
                    temp = wav.with_suffix(".wav.tmp")
                    try:
                        adapter.synthesize(row["text_vi_moderated"], temp)
                        frames = audio_info(temp)
                        # Metadata first: a crash after WAV rename can reuse it.
                        atomic_json(meta, {"fingerprint": key, "sha256": file_digest(temp), "frames": frames})
                        os.replace(temp, wav)
                    finally:
                        temp.unlink(missing_ok=True)
                else:
                    audio_info(wav)
                out.write(json.dumps({"index": index, "start_ms": row["start_ms"], "end_ms": row["end_ms"],
                    "text": row["text_vi_moderated"], "file": wav.name}, ensure_ascii=False) + "\n")
                out.flush()
                progress(job_dir, "tts", "TTS_GENERATING", index, total)
        check_cancel(job_dir)
        os.replace(manifest_tmp, manifest)
    finally:
        manifest_tmp.unlink(missing_ok=True)
    concatenate(job_dir, manifest)
    finish(job_dir, "tts", signature, ["voice/voice.manifest.jsonl", "voice.vi.wav"], total)
    progress(job_dir, "tts", "TTS_GENERATING", total, total)
