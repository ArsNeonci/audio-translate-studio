import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from audio_translate.transcription.pipeline import RATE, audio_piece, download, make_chunks, merge, validate_cookie_file


class PipelineTests(unittest.TestCase):
    def setUp(self):
        license_patch = patch("audio_translate.core.license_gate.assert_allowed", return_value=True)
        license_patch.start()
        self.addCleanup(license_patch.stop)
        session_patch = patch("audio_translate.transcription.youtube_session.cookies_for_download", return_value=None)
        session_patch.start()
        self.addCleanup(session_patch.stop)

    def test_downloader_requests_audio_only_without_conversion(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            job_dir = Path(folder)
            (job_dir / "source").mkdir()
            (job_dir / "job.json").write_text(json.dumps({"url": "https://www.youtube.com/watch?v=rwnyaH6cTDE", "name": "test"}), encoding="utf-8")
            options_seen = {}

            class FakeYDL:
                def __init__(self, options):
                    options_seen.update(options)

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def extract_info(self, _url, download):
                    self.assert_download = download
                    (job_dir / "source" / "audio.webm").write_bytes(b"audio")
                    return {"vcodec": "none", "title": "中文", "duration": 5}

            with patch.dict("os.environ", {"YTDLP_COOKIES_FILE": ""}), patch("yt_dlp.YoutubeDL", FakeYDL):
                self.assertEqual(download(job_dir).name, "audio.webm")
            self.assertEqual(options_seen["format"], "bestaudio")
            self.assertNotIn("postprocessors", options_seen)
            self.assertEqual(options_seen["js_runtimes"], {"node": {}})
            self.assertFalse(options_seen["no_warnings"])
            self.assertNotIn("cookiesfrombrowser", options_seen)
            self.assertNotIn("cookiefile", options_seen)

    def test_youtube_errors_and_explicit_cookie_configuration(self):
        from yt_dlp.utils import DownloadError

        cases = [
            ("Sign in to confirm you're not a bot", False, ".env.local"),
            ("Sign in to confirm you're not a bot", True, "xuất lại cookie"),
            ("HTTP Error 429: Too Many Requests", False, "HTTP 429"),
            ("HTTP Error 429: Too Many Requests", True, "HTTP 429"),
        ]
        for message, use_cookies, expected in cases:
            with self.subTest(message=message, cookies=use_cookies), tempfile.TemporaryDirectory() as folder:
                job_dir = Path(folder)
                (job_dir / "source").mkdir()
                (job_dir / "job.json").write_text(json.dumps({"url": "https://youtu.be/1JzKgwOESoM"}), encoding="utf-8")
                cookie_path = job_dir / "cookies.txt"
                cookie_path.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tTEST\tfake-value\n", encoding="utf-8")
                with patch.dict("os.environ", {"YTDLP_COOKIES_FILE": str(cookie_path) if use_cookies else ""}), patch("yt_dlp.YoutubeDL") as ydl:
                    ydl.return_value.__enter__.return_value.extract_info.side_effect = DownloadError(message)
                    with self.assertRaisesRegex(RuntimeError, expected):
                        download(job_dir)
                    options = ydl.call_args.args[0]
                    self.assertEqual(options.get("cookiefile"), str(cookie_path) if use_cookies else None)
                    self.assertNotIn("cookiesfrombrowser", options)

    def test_cookie_validation_does_not_disclose_malformed_cookie_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cookies.txt"
            for content in ("SID=fake-secret-value", "# Netscape HTTP Cookie File\nSID=fake-secret-value"):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError) as raised:
                    validate_cookie_file(path)
                self.assertNotIn("fake-secret-value", str(raised.exception))
            path.write_text("# Netscape HTTP Cookie File\n#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tfake-value\n", encoding="utf-8")
            validate_cookie_file(path)

    def test_silence_chunks_and_forced_overlap(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            working = Path(folder) / "working"
            working.mkdir()
            (working / "vad.jsonl").write_text("[0, 28000]\n[28000, 34000]\n[40000, 42000]\n", encoding="utf-8")
            chunks = make_chunks(Path(folder))
            self.assertEqual(len(chunks), 3)
            self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0, 30500))
            self.assertEqual((chunks[1]["start"], chunks[1]["own_start"]), (25500, 28000))
            self.assertEqual((chunks[2]["start"], chunks[2]["end"]), (40000, 42000))

    def test_pcm_overlap_reuses_bounded_tail(self):
        samples = np.arange(RATE * 8, dtype=np.int16)
        stream = io.BytesIO(samples.tobytes())
        first, cursor, tail = audio_piece(stream, 0, b"", 0, 5000)
        second, cursor, tail = audio_piece(stream, cursor, tail, 3000, 8000)
        self.assertEqual(len(first), RATE * 5)
        self.assertEqual(len(second), RATE * 5)
        self.assertEqual(cursor, RATE * 8)
        self.assertEqual(second[0], samples[RATE * 3] / 32768)
        self.assertLessEqual(len(tail), RATE * 6 * 2)

    def test_merge_keeps_global_order_and_unicode(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            job_dir = Path(folder)
            working = job_dir / "working"
            working.mkdir()
            (job_dir / "job.json").write_text(json.dumps({"status": "TRANSCRIBING", "progress": 90}), encoding="utf-8")
            rows = [
                [{"start_ms": 1000, "end_ms": 2000, "text": "你好。"},
                 {"start_ms": 4000, "end_ms": 5000, "text": "世界。"}],
                [{"start_ms": 1200, "end_ms": 1800, "text": "你好。"},
                 {"start_ms": 6000, "end_ms": 7000, "text": "再见。"}],
            ]
            for index, data in enumerate(rows):
                (working / f"chunk-{index:06d}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            merge(job_dir, [{}, {}])
            canonical = [json.loads(line) for line in (job_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["text"] for row in canonical], ["你好。", "世界。", "再见。"])
            self.assertEqual((job_dir / "transcript.zh.md").read_text(encoding="utf-8"), "你好。\n\n世界。再见。\n")


if __name__ == "__main__":
    unittest.main()
