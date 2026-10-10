import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
        # No gateway in tests: the bundled yt-dlp and the built-in client order.
        self.refresh = patch("audio_translate.transcription.ytdlp_update.refresh", return_value={"changed": False}).start()
        patch("audio_translate.transcription.ytdlp_update.activate", return_value=None).start()
        patch("audio_translate.transcription.ytdlp_update.local_manifest", return_value=None).start()
        self.addCleanup(patch.stopall)

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
            self.assertNotIn("extractor_args", options_seen)   # first attempt: YouTube's default client
            self.refresh.assert_called_once_with()             # the routine (throttled) check, not a forced one

    def test_youtube_errors_and_explicit_cookie_configuration(self):
        from yt_dlp.utils import DownloadError

        # (YouTube's answer, cookie file set, expected message, attempts made, last attempt's client)
        cases = [
            ("Sign in to confirm you're not a bot", False, "Kết nối YouTube", 2, ["mweb"]),
            ("Sign in to confirm you're not a bot", True, "xuất lại cookie", 5, ["tv"]),
            ("HTTP Error 429: Too Many Requests", False, "HTTP 429", 1, None),   # no more requests after a 429
            ("HTTP Error 429: Too Many Requests", True, "HTTP 429", 1, None),
        ]
        for message, use_cookies, expected, count, client in cases:
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
                    self.assertEqual(ydl.call_count, count)
                    options = ydl.call_args.args[0]
                    # The cookie file is used only by the attempts that ask for a sign-in, after the anonymous ones.
                    self.assertEqual(options.get("cookiefile"), str(cookie_path) if use_cookies and "Sign in" in message else None)
                    self.assertEqual(options.get("extractor_args", {}).get("youtube", {}).get("player_client"), client)
                    self.assertNotIn("cookiesfrombrowser", options)
                self.refresh.assert_called_with(force=True)   # every way failed: ask the gateway for a newer yt-dlp now
                rows = json.loads((job_dir / "working" / "download-attempts.json").read_text(encoding="utf-8"))["attempts"]
                self.assertEqual(len(rows), count)
                self.assertNotIn("fake-value", json.dumps(rows))

    def make_job(self, folder):
        job_dir = Path(folder); (job_dir / "source").mkdir()
        (job_dir / "job.json").write_text(json.dumps({"url": "https://youtu.be/8qH7C3NvAQE", "name": "t"}), encoding="utf-8")
        return job_dir

    def fake_youtube(self, job_dir, outcomes):
        """A YoutubeDL whose extract_info plays the given outcomes in order (an exception is raised, a dict is a success); records each attempt."""
        attempts = []

        class FakeYDL:
            def __init__(self, options):
                self.options, self.cookiejar = options, Mock()

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def extract_info(self, _url, download):
                client = self.options.get("extractor_args", {}).get("youtube", {}).get("player_client", [None])[0]
                attempts.append({"jar": self.cookiejar.set_cookie.call_count, "file": self.options.get("cookiefile"), "client": client})
                outcome = outcomes[len(attempts) - 1]
                if isinstance(outcome, Exception):
                    (job_dir / "source" / "audio.webm.part").write_bytes(b"half")   # what a failed attempt can leave behind
                    raise outcome
                self.leftover = (job_dir / "source" / "audio.webm.part").exists()
                attempts[-1]["leftover"] = self.leftover
                (job_dir / "source" / "audio.webm").write_bytes(b"audio")
                return outcome
        return FakeYDL, attempts

    def test_a_public_video_downloads_without_the_saved_youtube_sign_in(self):
        """A saved sign-in that YouTube refuses used to break every download ("The page needs to be reloaded") although the video is public."""
        with tempfile.TemporaryDirectory() as folder:
            job_dir = self.make_job(folder)
            fake, attempts = self.fake_youtube(job_dir, [{"vcodec": "none", "title": "t", "duration": 5}])
            with patch("audio_translate.transcription.youtube_session.cookies_for_download", return_value=[object()]) as session, patch("yt_dlp.YoutubeDL", fake):
                self.assertEqual(download(job_dir).name, "audio.webm")
            session.assert_not_called()                 # the browser profile is not even started
            self.assertEqual(attempts, [{"jar": 0, "file": None, "client": None, "leftover": False}])

    def test_another_client_is_tried_before_the_saved_sign_in(self):
        """Measured 2026-10-09: the default client was refused anonymously while mweb gave the audio."""
        from yt_dlp.utils import DownloadError
        with tempfile.TemporaryDirectory() as folder:
            job_dir = self.make_job(folder)
            fake, attempts = self.fake_youtube(job_dir, [DownloadError("Sign in to confirm you're not a bot"), {"vcodec": "none", "title": "t", "duration": 5}])
            with patch("audio_translate.transcription.youtube_session.cookies_for_download", return_value=[object()]) as session, patch("yt_dlp.YoutubeDL", fake):
                self.assertEqual(download(job_dir).name, "audio.webm")
            session.assert_not_called()
            self.assertEqual([(a["client"], a["jar"]) for a in attempts], [(None, 0), ("mweb", 0)])
            self.assertFalse(attempts[-1]["leftover"])  # the failed attempt's partial file was removed, not resumed into
            rows = json.loads((job_dir / "working" / "download-attempts.json").read_text(encoding="utf-8"))
            self.assertEqual([(r["client"], r["ok"]) for r in rows["attempts"]], [("default", False), ("mweb", True)])

    def test_the_saved_sign_in_is_used_only_when_youtube_asks_for_it(self):
        from yt_dlp.utils import DownloadError
        with tempfile.TemporaryDirectory() as folder:
            job_dir = self.make_job(folder)
            refused = DownloadError("Sign in to confirm you're not a bot")
            fake, attempts = self.fake_youtube(job_dir, [refused, refused, {"vcodec": "none", "title": "t", "duration": 5}])
            with patch("audio_translate.transcription.youtube_session.cookies_for_download", return_value=[object(), object()]) as session, patch("yt_dlp.YoutubeDL", fake):
                self.assertEqual(download(job_dir).name, "audio.webm")
            session.assert_called_once()
            self.assertEqual([(a["client"], a["jar"]) for a in attempts], [(None, 0), ("mweb", 0), (None, 2)])   # third attempt carries both cookies

    def test_a_refused_saved_sign_in_gets_a_clear_message_and_an_anonymous_refusal_keeps_the_original(self):
        from yt_dlp.utils import DownloadError
        reload = DownloadError("ERROR: [youtube] 8qH7C3NvAQE: The page needs to be reloaded.")
        bot = DownloadError("Sign in to confirm you're not a bot")
        with tempfile.TemporaryDirectory() as folder:
            job_dir = self.make_job(folder)
            fake, attempts = self.fake_youtube(job_dir, [bot, bot, reload, reload, reload])
            with patch("audio_translate.transcription.youtube_session.cookies_for_download", return_value=[object()]), patch("yt_dlp.YoutubeDL", fake):
                with self.assertRaisesRegex(RuntimeError, "từ chối phiên đăng nhập đã lưu"): download(job_dir)
            self.assertEqual(len(attempts), 5)
        with tempfile.TemporaryDirectory() as folder:
            job_dir = self.make_job(folder)
            fake, attempts = self.fake_youtube(job_dir, [reload, reload])
            with patch("yt_dlp.YoutubeDL", fake):
                with self.assertRaisesRegex(RuntimeError, "Không tải được audio YouTube: .*reloaded"): download(job_dir)   # no sign-in involved: the plain error
            self.assertEqual(len(attempts), 2)   # no saved sign-in: the attempts that need one are skipped

    def test_the_client_order_from_the_gateway_is_followed_and_an_update_is_announced(self):
        from yt_dlp.utils import DownloadError
        plan = [{"client": "tv", "cookies": False}, {"client": "ios", "cookies": False}]
        with tempfile.TemporaryDirectory() as folder:
            job_dir = self.make_job(folder)
            fake, attempts = self.fake_youtube(job_dir, [DownloadError("Requested format is not available"), DownloadError("Requested format is not available")])
            with patch("audio_translate.transcription.ytdlp_update.attempts", return_value=plan), patch("yt_dlp.YoutubeDL", fake):
                self.refresh.return_value = {"changed": True}
                with self.assertRaisesRegex(RuntimeError, "Đã nhận bản cập nhật bộ tải YouTube; bấm Thử lại"): download(job_dir)
            self.assertEqual([a["client"] for a in attempts], ["tv", "ios"])

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
