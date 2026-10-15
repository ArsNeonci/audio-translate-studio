"""Subtitles (video/subtitles.py): timed from the voice itself, cut at sentence ends and clauses, at most two lines, never overlapping,
and in the SubRip form YouTube accepts."""
from audio_translate.core.error_ids import AppError
import json
from pathlib import Path
import re
import tempfile
import unittest

import numpy as np
import soundfile as sf

from audio_translate.video import subtitles as sub

LONG = ('Bạn cùng phòng của tôi quen được một anh bạn trai hoàn hảo, ngày nào cũng đồ ăn vặt nhập khẩu, hoa tươi, trang sức không ngừng nghỉ. '
        'Mãi cho đến khi tôi phát hiện những món đồ ký túc xá nam bị mất đều xuất hiện trên bàn của cô ta! Tôi lén nói với cô ta: "Bạn trai cậu có thể là kẻ trộm đấy." '
        'Cô ta lập tức lật mặt: "Cậu chỉ là ghen tị thôi?"')


class SubtitleTests(unittest.TestCase):
    def test_a_short_unit_is_one_cue_at_the_right_time_and_units_follow_each_other_with_their_pauses(self):
        cues = sub.build([('Xin chào.', 2000, 300), ('Tạm biệt các bạn.', 3000, 0)])
        self.assertEqual(cues, [(0, 2000, 'Xin chào.'), (2300, 5300, 'Tạm biệt các bạn.')])

    def test_a_long_paragraph_is_cut_at_sentence_ends_and_clauses_within_the_limit(self):
        cues = sub.build([(LONG, 40_000, 0)], {'max_chars': 84})
        self.assertGreater(len(cues), 4)
        for start, end, text in cues:
            self.assertLessEqual(len(text.replace('\n', ' ')), 84, text)
            self.assertLessEqual(text.count('\n'), 1)
        self.assertEqual(cues[0][0], 0); self.assertEqual(cues[-1][1], 40_000)         # the cues fill exactly the time of the unit
        for (a, b, _), (c, d, _) in zip(cues, cues[1:]):
            self.assertEqual(b, c); self.assertLess(a, b)                                  # contiguous, never overlapping
        self.assertTrue(cues[0][2].replace('\n', ' ').endswith(','))                        # the first sentence is longer than the limit: its first cue ends at a clause
        self.assertEqual(' '.join(t.replace('\n', ' ') for _, _, t in cues), LONG)         # nothing lost, nothing added

    def test_time_inside_a_unit_follows_the_characters(self):
        cues = sub.build([('A' * 20 + '. ' + 'B' * 60 + '.', 8000, 0)], {'max_chars': 62})
        self.assertEqual([c[2] for c in cues], ['A' * 20 + '.', 'B' * 60 + '.'])
        self.assertAlmostEqual((cues[0][1] - cues[0][0]) / 8000, 21 / 83, delta=0.01)

    def test_a_cue_stays_up_for_the_least_time_but_never_into_the_next_cue(self):
        cues = sub.build([('Vâng.', 400, 100), ('Được rồi.', 400, 5000), ('Hết.', 3000, 0)], {'min_seconds': 1.0})
        self.assertEqual(cues[0], (0, 500, 'Vâng.'))                  # the next cue starts at 500: no room to wait the full second
        self.assertEqual(cues[1], (500, 1500, 'Được rồi.'))          # room after it (5 s pause): up for a whole second
        self.assertEqual(cues[2][0], 5900)

    def test_no_cue_outlasts_the_voice(self):
        cues = sub.build([('Hết.', 300, 0)], {'min_seconds': 2.0}, total_ms=300)
        self.assertEqual(cues, [(0, 300, 'Hết.')])
        self.assertEqual(sub.build([('Hết.', 300, 0)], {'min_seconds': 2.0}), [(0, 2000, 'Hết.')])      # unknown total: the least time applies

    def test_two_lines_break_near_the_middle_only_when_long(self):
        self.assertEqual(sub.two_lines('ngắn thôi'), 'ngắn thôi')
        text = 'một hai ba bốn năm sáu bảy tám chín mười mười một mười hai'
        first, second = sub.two_lines(text).split('\n')
        self.assertLess(abs(len(first) - len(second)), 12); self.assertEqual(first + ' ' + second, text)

    def test_unknown_lengths_share_the_rest_of_the_voice(self):
        cues = sub.build([('Một hai ba.', None, 0), ('Bốn năm sáu bảy tám chín.', None, 0)], total_ms=10_000)
        self.assertEqual(cues[-1][1], 10_000); self.assertEqual(cues[0][0], 0)
        with self.assertRaises(AppError): sub.build([('x', None, 0)])

    def test_srt_text_is_what_youtube_reads(self):
        text = sub.to_srt([(0, 4160, 'Xin chào'), (3_723_599, 3_725_000, 'dòng\nhai')])
        self.assertEqual(text, '1\n00:00:00,000 --> 00:00:04,160\nXin chào\n\n2\n01:02:03,599 --> 01:02:05,000\ndòng\nhai\n\n')
        self.assertTrue(re.fullmatch(r'(\d+\n\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}\n[^\n]+(\n[^\n]+)?\n\n)+', text))

    def test_the_settings_are_checked(self):
        self.assertEqual(sub.validate(None), {'max_chars': 84, 'min_seconds': 1.0})
        self.assertEqual(sub.validate({'max_chars': 60}), {'max_chars': 60, 'min_seconds': 1.0})
        for bad in ([], {'max_chars': 5}, {'max_chars': 500}, {'min_seconds': 0}, {'min_seconds': 9}, {'max_chars': '84'}, {'max_chars': True}, {'min_seconds': float('nan')}):
            with self.assertRaises(ValueError, msg=repr(bad)): sub.validate(bad)

    def test_it_reads_a_manifest_with_frames_or_falls_back_to_the_wav_files_and_checks_the_voice_length(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = Path(folder)
            for name, seconds in (('000001.wav', 2.0), ('000002.wav', 3.0)):
                sf.write(str(voice / name), np.zeros(int(48000 * seconds), dtype=np.int16), 48000, subtype='PCM_16')
            rows = [{'index': 1, 'text': 'Câu một.', 'file': '000001.wav', 'gap_after_ms': 500}, {'index': 2, 'text': 'Câu hai.', 'file': '000002.wav', 'gap_after_ms': 0}]
            (voice / 'm.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            out = sub.make(voice / 'm.jsonl', voice, total_ms=5500)               # no frames: the segment files give the lengths
            self.assertIn('00:00:02,500 --> 00:00:05,500', out)
            rows[0]['frames'] = 96000; rows[1]['frames'] = 144000                 # frames recorded: the files are not needed
            (voice / 'm.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            self.assertEqual(sub.make(voice / 'm.jsonl', None, total_ms=5500), out)
            with self.assertRaises(AppError): sub.make(voice / 'm.jsonl', None, total_ms=60_000)    # a manifest of another voice
            target = voice / 'a.srt'
            self.assertEqual(sub.write(target, voice / 'm.jsonl', None, total_ms=5500), 2)
            self.assertEqual(target.read_bytes()[:3], b'1\n0'); self.assertNotIn(b'\r', target.read_bytes())


if __name__ == '__main__':
    unittest.main()
