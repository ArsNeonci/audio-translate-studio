"""Real local Hy-MT2 GGUF → replacement → VieNeu test, isolated from user rules/jobs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
from audio_translate.core.storage import ROOT, atomic_json, file_digest, read_json, rows
from audio_translate.moderation.rules import ReplacementRules
from audio_translate.workflow.postprocess import translate, moderate, synthesize


def main():
    data = ROOT / "data" / "verification" / "acceptance"
    os.environ.setdefault("HF_HOME", str(ROOT / "data" / "hf-cache"))
    data.mkdir(parents=True, exist_ok=True)
    pointer = data / "current-job.txt"
    job_id = pointer.read_text().strip() if pointer.exists() else str(uuid.uuid4())
    pointer.write_text(job_id, encoding="ascii")
    job = data / "jobs" / job_id
    (job / "working").mkdir(parents=True, exist_ok=True)
    if not (job / "job.json").exists():
        atomic_json(job / "job.json", {"id": job_id, "name": "Acceptance · Hy-MT2 GGUF → Rules → VieNeu", "url": "",
            "status": "TRANSCRIPTION_COMPLETED", "progress": 25, "duration_ms": 4000, "workflow_version": 2,
            "created_at": "2026-10-02T00:00:00Z", "error": None, "stages": {"transcription": {"percent": 100}}})
        (job / "transcript.zh.jsonl").write_text('{"start_ms":0,"end_ms":1900,"text":"你好，欢迎来到我们的频道。"}\n{"start_ms":2000,"end_ms":4000,"text":"今天我们开始学习。"}\n', encoding="utf-8")
        (job / "transcript.zh.md").write_text("你好，欢迎来到我们的频道。\n\n今天我们开始学习。\n", encoding="utf-8")
    print("JOB", job_id, flush=True)
    translate(job)
    print("TRANSLATION", list(rows(job / "transcript.vi.jsonl", "text_vi")), flush=True)
    service = ReplacementRules(data / "config")
    if not service.read():
        first = next(rows(job / "transcript.vi.jsonl", "text_vi"))[1]["text_vi"]
        service.mutate("add", {"source": first, "replacement": "Xin chào các bạn."})
    vi_sha = file_digest(job / "transcript.vi.jsonl")
    moderate(job, service)
    assert file_digest(job / "transcript.vi.jsonl") == vi_sha
    print("MODERATION", read_json(job / "moderation-result.json"), flush=True)
    synthesize(job)
    import soundfile as sf
    info = sf.info(str(job / "voice.vi.wav"))
    assert info.frames > 0 and info.samplerate == 48000
    assert len(list(rows(job / "voice" / "voice.manifest.jsonl", "text"))) == 2
    print("REAL E2E OK", {"frames": info.frames, "seconds": info.duration, "wav": str(job / "voice.vi.wav")}, flush=True)


if __name__ == "__main__":
    main()
