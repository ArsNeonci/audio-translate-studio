import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audio_translate.core.storage import atomic_json, read_json
from audio_translate.tts import voice_styles
from audio_translate.tts.adapters import adapter_settings
from audio_translate.workflow.postprocess import synthesize


def row(start, end, text):
    return {"start_ms": start, "end_ms": end, "text_vi_moderated": text}


class FakeTTS:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, output):
        self.calls.append(text)
        sf.write(str(output), np.ones(240, dtype=np.float32) * .05, 48000, format="WAV", subtype="PCM_16")


class VoiceStyleTests(unittest.TestCase):
    def test_default_keeps_one_unit_per_row_without_gaps(self):
        rows = [(1, row(0, 900, "Một,")), (2, row(1000, 1900, "hai."))]
        self.assertEqual(list(voice_styles.units(rows, None)), [(1, [rows[0][1]], "Một,", None), (2, [rows[1][1]], "hai.", None)])
        self.assertIsNone(voice_styles.settings(None))
        self.assertIsNone(voice_styles.settings("default"))

    def test_rows_join_until_sentence_end_and_gaps_follow_style(self):
        style = voice_styles.settings("rebirth")
        rows = [(1, row(0, 900, "Kiếp trước tôi,")), (2, row(950, 1800, "đã chết.")), (3, row(1900, 2500, "Thật sao?")),
                (4, row(2600, 3000, "Ừ.")), (5, row(6000, 7000, "Ba năm sau."))]
        result = list(voice_styles.units(rows, style))
        self.assertEqual([(u[0], u[2], u[3]) for u in result], [
            (1, "Kiếp trước tôi, đã chết.", style["gap_ms"]),
            (3, "Thật sao?", style["long_gap_ms"]),
            (4, "Ừ.", style["long_gap_ms"]),  # scene break before row 5
            (5, "Ba năm sau.", 0)])

    def test_units_are_capped(self):
        rows = [(i, row(i * 10, i * 10 + 5, "chữ " * 20)) for i in range(1, 6)]
        units = list(voice_styles.units(rows, voice_styles.settings("drama")))
        self.assertGreater(len(units), 1)
        self.assertTrue(all(len(u[2]) <= voice_styles.MAX_UNIT_CHARS for u in units))

    def test_cues_only_replace_standalone_interjections(self):
        self.assertEqual(voice_styles.add_cues("Ha ha, cô ta thua rồi."), "[cười], cô ta thua rồi.")
        self.assertEqual(voice_styles.add_cues("Haizz, lại nữa."), "[thở dài], lại nữa.")
        self.assertEqual(voice_styles.add_cues("Hôm nay hai người hiểu chưa? Ôi trời."), "Hôm nay hai người hiểu chưa? Ôi trời.")
        self.assertEqual(voice_styles.add_cues("Hà Nội và Hải Phòng."), "Hà Nội và Hải Phòng.")

    def test_unknown_style_is_rejected(self):
        with self.assertRaises(ValueError):
            voice_styles.validate("horror")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_finish_audio_trims_and_changes_tempo(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "a.wav"
            tone = .3 * np.sin(np.arange(48000) * 2 * np.pi * 220 / 48000).astype(np.float32)
            sf.write(str(path), np.concatenate([np.zeros(24000, np.float32), tone, np.zeros(24000, np.float32)]), 48000, subtype="PCM_16")
            voice_styles.finish_audio(path, {"tempo": 1.25})
            frames = sf.info(str(path)).frames
            self.assertAlmostEqual(frames, (48000 + 2 * 1440) / 1.25, delta=2400)


class StyledSynthesisTests(unittest.TestCase):
    def setUp(self):
        license_patch = patch("audio_translate.core.license_gate.assert_allowed", return_value=True)
        license_patch.start()
        self.addCleanup(license_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name) / "jobs" / "test"
        (self.job / "working").mkdir(parents=True)
        rows = [row(0, 900, "Tôi mở cửa,"), row(1000, 1900, "nhìn thấy anh ta."), row(2000, 2900, "Ha ha!")]
        (self.job / "transcript.vi.moderated.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def run_style(self, style):
        atomic_json(self.job / "job.json", {"status": "MODERATION_COMPLETED", "workflow_version": 2, "selected_voice_style": style})
        tts = FakeTTS()
        synthesize(self.job, tts)
        return tts, [json.loads(line) for line in (self.job / "voice" / "voice.manifest.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_styled_job_groups_sentences_and_inserts_pauses(self):
        tts, manifest = self.run_style("drama")
        self.assertEqual(tts.calls, ["Tôi mở cửa, nhìn thấy anh ta.", "[cười]!"])
        self.assertEqual([(m["index"], m["rows"], m["gap_after_ms"]) for m in manifest], [(1, 2, 170), (3, 1, 0)])
        self.assertEqual(sf.info(str(self.job / "voice.vi.wav")).frames, 2 * 240 + 170 * 48)
        self.assertEqual(read_json(self.job / "working" / "adapters.json")["tts"]["style"]["id"], "drama")

    def test_default_job_config_has_no_style(self):
        tts, manifest = self.run_style("default")
        self.assertEqual(len(tts.calls), 3)
        self.assertNotIn("gap_after_ms", manifest[0])
        self.assertNotIn("style", adapter_settings(self.job)["tts"])


if __name__ == "__main__":
    unittest.main()
