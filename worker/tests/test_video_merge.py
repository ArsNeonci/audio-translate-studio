"""Video merge (video/merge.py) on real, tiny clips made with ffmpeg: the clips are looped and cut to the voice, identical clips are
copied without re-encoding, different ones are encoded once with black bars, and moved or broken clips give a clear error."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audio_translate.core.errors import classify, effective_steps, initial_steps
from audio_translate.video import merge

FFMPEG = shutil.which('ffmpeg') and shutil.which('ffprobe')


def clip(path, seconds, size='320x240', rate=25, codec='libx264'):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc=duration={seconds}:size={size}:rate={rate}',
                    '-f', 'lavfi', '-i', f'sine=duration={seconds}', '-c:v', codec, '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(path)], check=True)
    return str(path)


def voice(path, seconds):
    sf.write(str(path), (np.sin(np.arange(int(48000 * seconds)) / 20) * 8000).astype(np.int16), 48000, subtype='PCM_16')
    return path


def streams(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(FFMPEG, 'ffmpeg is not on PATH')
class VideoMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = self.root / 'job'; (self.job / 'working').mkdir(parents=True)
        self.results = self.root / 'results'; self.results.mkdir()
        for target in ('audio_translate.core.license_gate.assert_allowed',):
            p = patch(target, return_value=True); p.start(); self.addCleanup(p.stop)
        p = patch('audio_translate.workflow.results.destination', return_value=self.results); p.start(); self.addCleanup(p.stop)

    def run_merge(self, files, seconds, resolution='keep', quality='high'):
        voice(self.job / 'voice.vi.wav', seconds)
        settings = merge.validate({'files': [{'path': f} for f in files], 'resolution': resolution, 'quality': quality})
        (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings, 'steps': {}}), encoding='utf-8')
        merge.merge(self.job)
        return streams(self.job / merge.OUTPUT), json.loads((self.job / 'job.json').read_text(encoding='utf-8'))

    def test_a_short_clip_is_repeated_and_cut_to_the_voice_without_re_encoding(self):
        info, job = self.run_merge([clip(self.root / 'a.mp4', 3)], 10)
        self.assertEqual(job['video_plan']['mode'], 'copy'); self.assertEqual(job['video_plan']['repeats'], 4)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video'); audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
        self.assertEqual((video['width'], video['height'], audio['codec_name']), (320, 240, 'aac'))
        self.assertAlmostEqual(float(info['format']['duration']), 10, delta=0.15)
        self.assertEqual(len(info['streams']), 2)                           # the clip's own sound is dropped
        self.assertEqual(job['stages']['video']['percent'], 100)

    def test_a_long_clip_is_cut(self):
        info, _ = self.run_merge([clip(self.root / 'long.mp4', 8)], 3)
        self.assertAlmostEqual(float(info['format']['duration']), 3, delta=0.15)

    def test_identical_clips_are_joined_in_order_without_re_encoding(self):
        files = [clip(self.root / 'a.mp4', 2), clip(self.root / 'b.mp4', 2)]
        info, job = self.run_merge(files, 6)
        self.assertEqual(job['video_plan']['mode'], 'copy')
        self.assertAlmostEqual(float(info['format']['duration']), 6, delta=0.15)

    def test_different_clips_are_encoded_once_with_black_bars(self):
        files = [clip(self.root / 'wide.mp4', 2, '640x360'), clip(self.root / 'tall.mkv', 2, '240x320', 30)]
        info, job = self.run_merge(files, 7, resolution='keep', quality='light')
        self.assertEqual(job['video_plan']['mode'], 'encode')
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        self.assertEqual((video['width'], video['height'], video['codec_name']), (640, 360, 'h264'))   # the first clip sets the frame
        self.assertAlmostEqual(float(info['format']['duration']), 7, delta=0.2)
        self.assertFalse((self.job / merge.BASE).exists())                  # the encoded base clip is not left behind

    def test_resolutions_never_blow_a_picture_up_and_the_size_is_estimated(self):
        small = merge.probe(clip(self.root / 's.mp4', 1, '854x480'))
        self.assertEqual(merge.resolutions([small]), ['keep', '480'])
        with self.assertRaises(ValueError): merge.validate({'files': [small['path']], 'resolution': '720', 'quality': 'high'})
        plan = merge.plan([small], '480', 'medium', 3_600_000)
        self.assertEqual((plan['mode'], plan['height'], plan['video_kbps']), ('encode', 480, 1200))
        self.assertAlmostEqual(plan['size_bytes'] / 1024 ** 2, (1200 + 128) * 1000 / 8 * 3600 * 1.02 / 1024 ** 2, delta=1)
        self.assertIsNone(merge.plan([small], 'keep', 'high', None)['size_bytes'])   # no voice yet: only the size per hour

    def test_moved_or_broken_clips_give_a_clear_error(self):
        with self.assertRaises(merge.VideoError) as missing: merge.probe(str(self.root / 'gone.mp4'))
        self.assertEqual(classify(missing.exception), 'VIDEO_MISSING')
        (self.root / 'broken.mp4').write_bytes(b'not a video')
        with self.assertRaises(merge.VideoError) as broken: merge.probe(str(self.root / 'broken.mp4'))
        self.assertEqual(classify(broken.exception), 'VIDEO_UNREADABLE')
        (self.root / 'notes.txt').write_text('x')
        with self.assertRaises(merge.VideoError) as kind: merge.probe(str(self.root / 'notes.txt'))
        self.assertEqual(classify(kind.exception), 'VIDEO_UNREADABLE')
        with self.assertRaises(merge.VideoError): merge.probe('relative.mp4')
        for bad in (None, {}, {'files': []}, {'files': ['x'] * 51}, {'files': [1]}, {'files': ['a.mp4'], 'resolution': '4k'}, {'files': ['a.mp4'], 'quality': 'best'}):
            with self.assertRaises(ValueError, msg=repr(bad)): merge.validate(bad)

    def test_a_clip_moved_after_it_was_chosen_fails_the_merge(self):
        path = clip(self.root / 'a.mp4', 2)
        voice(self.job / 'voice.vi.wav', 3)
        settings = merge.validate({'files': [path]})
        (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings}), encoding='utf-8')
        Path(path).rename(self.root / 'moved.mp4')
        with self.assertRaises(merge.VideoError) as error: merge.merge(self.job)
        self.assertEqual(error.exception.code, 'VIDEO_MISSING')

    def test_the_dialog_answer_is_split_into_paths_in_order(self):
        from audio_translate.api.dialog import _split
        self.assertEqual(_split('C:\\v\\a.mp4\x00\x00'), ['C:\\v\\a.mp4'])
        self.assertEqual(_split('C:\\v\x00b.mp4\x00a.mov\x00\x00'), ['C:\\v\\b.mp4', 'C:\\v\\a.mov'])
        self.assertEqual(_split('D:\\\x00x.mp4\x00y.mp4\x00\x00'), ['D:\\x.mp4', 'D:\\y.mp4'])
        self.assertEqual(_split('\x00'), [])

    def test_only_runs_with_videos_have_the_video_step(self):
        self.assertEqual(effective_steps({}), ['DOWNLOAD', 'TRANSCRIPTION', 'TRANSLATION', 'MODERATION', 'TTS'])
        self.assertEqual(effective_steps({'video': {'files': []}})[-1], 'VIDEO')
        self.assertEqual(effective_steps({'tool_steps': ['VIDEO']}), ['VIDEO'])
        self.assertNotIn('VIDEO', initial_steps({}))
        self.assertIn('VIDEO', initial_steps({'video': {'files': []}}))


if __name__ == '__main__':
    unittest.main()
