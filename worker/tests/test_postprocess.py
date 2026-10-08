import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from unittest.mock import patch, Mock

import numpy as np
import soundfile as sf

from audio_translate.tts.adapters import TranslationAdapter, adapter_settings
from audio_translate.workflow.postprocess import translate, moderate, synthesize
from audio_translate.moderation.rules import ReplaceEngine, ReplacementRules
from audio_translate.core.storage import atomic_json, file_digest, file_lock, LockedError, read_json


class FakeTranslator:
    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after

    def translate(self, texts):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("simulated translation failure")
        self.calls.extend(texts)
        return ["Xin chào thế giới. " + text for text in texts]


class FakeTTS:
    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after

    def synthesize(self, text, output):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("simulated TTS failure")
        self.calls.append(text)
        sf.write(str(output), np.ones(240, dtype=np.float32) * .05, 48000, format="WAV", subtype="PCM_16")


class PostprocessTests(unittest.TestCase):
    def setUp(self):
        license_patch = patch("audio_translate.core.license_gate.assert_allowed", return_value=True)
        license_patch.start()
        self.addCleanup(license_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = self.root / "jobs" / "test"
        (self.job / "working").mkdir(parents=True)
        atomic_json(self.job / "job.json", {"status": "TRANSCRIPTION_COMPLETED", "workflow_version": 2})
        self.source = [{"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": f"你好，世界{i}。"} for i in range(5)]
        self.write_rows("transcript.zh.jsonl", self.source)
        settings = adapter_settings(self.job)
        settings["translation"]["batch_size"] = 1
        atomic_json(self.job / "working" / "adapters.json", settings)
        self.rules = ReplacementRules(self.root / "config")

    def write_rows(self, name, rows):
        (self.job / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def read_rows(self, name):
        return [json.loads(line) for line in (self.job / name).read_text(encoding="utf-8").splitlines()]

    def test_literal_longest_nfc_no_cascade(self):
        engine = ReplaceEngine([
            {"id": "short", "source": "thế", "replacement": "short"},
            {"id": "long", "source": "thế giới", "replacement": "a.b"},
            {"id": "literal", "source": "a.b", "replacement": "OK"},
        ])
        text, counts = engine.apply(unicodedata.normalize("NFD", "thế giới a.b aXb"))
        self.assertEqual(text, "a.b OK aXb")
        self.assertEqual(counts, {"long": 1, "literal": 1})
        self.assertTrue(unicodedata.is_normalized("NFC", text))

    def test_translation_resume_no_loss_or_timestamp_changes(self):
        translator = FakeTranslator(fail_after=2)
        with self.assertRaises(RuntimeError):
            translate(self.job, translator)
        self.assertFalse((self.job / "transcript.vi.jsonl").exists())
        resumed = FakeTranslator()
        translate(self.job, resumed)
        self.assertEqual(resumed.calls, [row["text"] for row in self.source[2:]])
        translated = self.read_rows("transcript.vi.jsonl")
        self.assertEqual(len(translated), len(self.source))
        self.assertEqual([(r["start_ms"], r["end_ms"], r["text_zh"]) for r in translated],
                         [(r["start_ms"], r["end_ms"], r["text"]) for r in self.source])
        translate(self.job, FakeTranslator(fail_after=0))

    def test_moderation_snapshot_resume_unlock_and_original_immutable(self):
        translate(self.job, FakeTranslator())
        before = file_digest(self.job / "transcript.vi.jsonl")
        rule = self.rules.mutate("add", {"source": "thế giới", "replacement": "các bạn"})["rules"][0]
        def fail(index):
            if index == 2:
                raise RuntimeError("simulated moderation failure")
        with self.assertRaises(RuntimeError):
            moderate(self.job, self.rules, after_segment=fail)
        self.assertFalse(self.rules.list()["locked"])
        self.assertEqual(read_json(self.job / "job.json")["status"], "FAILED")
        self.rules.mutate("edit", {**rule, "replacement": "NEW RULE"})
        with patch.object(ReplaceEngine, "apply", wraps=ReplaceEngine([rule]).apply) as apply:
            moderate(self.job, self.rules)
            self.assertEqual(apply.call_count, 3)
        output = self.read_rows("transcript.vi.moderated.jsonl")
        self.assertTrue(all("các bạn" in row["text_vi_moderated"] for row in output))
        self.assertEqual(file_digest(self.job / "transcript.vi.jsonl"), before)
        result = read_json(self.job / "moderation-result.json")
        self.assertEqual((result["total_segments"], result["modified_segments"], result["total_replacements"]), (5, 5, 5))

    def test_cross_process_crud_cannot_bypass_moderation_lock(self):
        translate(self.job, FakeTranslator())
        rule = self.rules.mutate("add", {"source": "thế giới", "replacement": "bạn"})["rules"][0]
        def check(index):
            if index != 1:
                return
            self.assertEqual(read_json(self.job / "job.json")["status"], "MODERATING")
            for action in ("add", "edit", "delete"):
                result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "rules.py")],
                    input=json.dumps({"action": action, "id": rule["id"], "source": "a", "replacement": "b"}),
                    capture_output=True, text=True, encoding="utf-8", check=True,
                    env={**os.environ, "AUDIO_DATA_DIR": str(self.root), "PYTHONUTF8": "1"})
                self.assertEqual(json.loads(result.stdout)["status"], 409)
        moderate(self.job, self.rules, after_segment=check)
        self.assertFalse(self.rules.list()["locked"])
        self.rules.mutate("delete", {"id": rule["id"]})

    def test_tts_only_moderated_text_resume_order_and_no_upstream_rerun(self):
        translate(self.job, FakeTranslator())
        self.rules.mutate("add", {"source": "thế giới", "replacement": "các bạn"})
        moderate(self.job, self.rules)
        immutable = {"transcript.vi.jsonl": file_digest(self.job / "transcript.vi.jsonl")}
        with self.assertRaises(RuntimeError):
            synthesize(self.job, FakeTTS(fail_after=2))
        # The fake translator copies the Chinese source into its output. The voice step takes those characters out once (tts/voice_check.py)
        # before it starts; after that the moderated text must stay exactly as it is, however many times the step is resumed.
        immutable["transcript.vi.moderated.jsonl"] = file_digest(self.job / "transcript.vi.moderated.jsonl")
        self.assertTrue(all("你" not in r["text_vi_moderated"] for r in self.read_rows("transcript.vi.moderated.jsonl")))
        wav_times = [(self.job / "voice" / f"{i:06d}.wav").stat().st_mtime_ns for i in (1, 2)]
        resumed = FakeTTS()
        translate(self.job, FakeTranslator(fail_after=0))
        with patch.object(ReplaceEngine, "apply", side_effect=AssertionError("reran moderation")):
            moderate(self.job, self.rules)
        synthesize(self.job, resumed)
        self.assertEqual(len(resumed.calls), 3)
        self.assertTrue(all("các bạn" in text and "thế giới" not in text for text in resumed.calls))
        self.assertEqual(wav_times, [(self.job / "voice" / f"{i:06d}.wav").stat().st_mtime_ns for i in (1, 2)])
        manifest = self.read_rows("voice/voice.manifest.jsonl")
        self.assertEqual([r["index"] for r in manifest], list(range(1, 6)))
        self.assertEqual([(r["start_ms"], r["end_ms"]) for r in manifest], [(r["start_ms"], r["end_ms"]) for r in self.source])
        self.assertEqual(sf.info(str(self.job / "voice.vi.wav")).frames, 5 * 240)
        for name, sha in immutable.items():
            self.assertEqual(file_digest(self.job / name), sha)
        synthesize(self.job, FakeTTS(fail_after=0))

    def test_tts_rejects_unmoderated_input(self):
        translate(self.job, FakeTranslator())
        with self.assertRaises(FileNotFoundError):
            synthesize(self.job, FakeTTS())

    def test_orchestrator_skips_finished_stages_after_tts_failure(self):
        from audio_translate.workflow.orchestrator import run
        (self.job / "transcript.zh.md").write_text("你好", encoding="utf-8")
        translate(self.job, FakeTranslator())
        moderate(self.job, self.rules)
        with patch("audio_translate.workflow.orchestrator.subprocess.run", return_value=Mock(returncode=1)) as child:
            self.assertEqual(run(self.job), 1)
            self.assertEqual(child.call_count, 1)
            self.assertEqual(child.call_args.args[0][-1], "tts")
        synthesize(self.job, FakeTTS())
        with patch("audio_translate.workflow.orchestrator.subprocess.run", side_effect=AssertionError("completed stage was restarted")):
            self.assertEqual(run(self.job), 0)

    def test_long_qwen_source_split_is_lossless(self):
        from audio_translate.translation.hymt_translation import default_settings
        adapter = TranslationAdapter({**default_settings(), "source_tokens": 10})
        class Model:
            def tokenize(self, text, **kwargs):
                return list(text.decode('utf-8'))
        adapter.model = Model()
        text = "今天我们开始学习。" * 100
        parts = list(adapter.parts(text))
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(p) <= 10 for p in parts))

    def test_rules_lock_is_released_after_process_crash(self):
        command = "from audio_translate.core.storage import file_lock; import sys,time; from pathlib import Path; c=file_lock(Path(sys.argv[1])); c.__enter__(); print('locked',flush=True); time.sleep(60)"
        process = subprocess.Popen([sys.executable, "-u", "-c", command, str(self.rules.lock_path)], cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with self.assertRaises(LockedError):
                self.rules.mutate("add", {"source": "a", "replacement": "b"})
        finally:
            process.kill(); process.wait(); process.stdout.close()
        self.rules.mutate("add", {"source": "a", "replacement": "b"})

    def test_atomic_rules_write_retries_windows_reader_conflict(self):
        original_replace = os.replace
        attempts = []
        def replace(source, target):
            attempts.append(target)
            if len(attempts) == 1:
                raise PermissionError("simulated Windows reader")
            return original_replace(source, target)
        with patch("audio_translate.core.storage.os.replace", side_effect=replace):
            self.rules.mutate("add", {"source": "test", "replacement": "saved"})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.rules.read()[0]["replacement"], "saved")


if __name__ == "__main__":
    unittest.main()
