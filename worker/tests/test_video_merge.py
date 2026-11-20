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


def black_clip(path, seconds, size='320x240', rate=25):
    """A black picture: the only thing that can light a pixel in the output is a drawn subtitle (or logo)."""
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=black:size={size}:rate={rate}:duration={seconds}', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)
    return str(path)


def lit_pixels(path, second):
    """How many pixels of the frame at `second` are clearly not black."""
    out = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(second), '-i', str(path), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
                         capture_output=True, check=True).stdout
    return sum(1 for value in out if value > 90)


def write_srt(job_dir, job):
    path = Path(job_dir) / merge.SUBTITLE_FILE
    path.write_text(SRT, encoding='utf-8')
    return path


SRT = '1\n00:00:01,000 --> 00:00:02,000\nXXXXXXXX\n\n2\n00:00:04,500 --> 00:00:05,500\nXXXXXXXX\n'


@unittest.skipUnless(FFMPEG, 'ffmpeg is not on PATH')
class UltraFastMergeTests(unittest.TestCase):
    """Ultra fast: x264 ultrafast, and with the subtitles ticked the merge draws them itself in ONE encoding (no BURN step, one file)."""
    setUp = VideoMergeTests.setUp

    def run_ultra(self, files, seconds, burn=True, ultra=True, **extra):
        voice(self.job / 'voice.vi.wav', seconds)
        settings = merge.validate({'files': [{'path': f} for f in files], 'burn': burn, 'ultra': ultra, **extra})
        (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings, 'steps': {}}), encoding='utf-8')
        with patch.object(merge, '_write_subtitles', write_srt): merge.merge(self.job)
        return json.loads((self.job / 'job.json').read_text(encoding='utf-8'))

    def preset_of(self, path):
        """x264 writes the parameters it ended up with into the stream; subme is 0 for ultrafast, 2 for veryfast and 7 for medium."""
        import re
        found = re.search(rb'subme=(\d)', Path(path).read_bytes())
        return {0: 'ultrafast', 2: 'veryfast', 7: 'medium'}.get(int(found.group(1))) if found else None

    def test_a_short_clip_is_drawn_once_then_one_encoding_loops_it_and_draws_the_subtitles(self):
        job = self.run_ultra([black_clip(self.root / 'a.mp4', 2)], 8)
        out = self.job / merge.BURN_OUTPUT
        info = streams(out)
        self.assertEqual([s['codec_name'] for s in info['streams']], ['h264', 'aac'])
        self.assertAlmostEqual(float(info['format']['duration']), 8, delta=0.2)
        self.assertEqual((job['video_plan']['mode'], job['video_plan']['ultra']), ('encode', True))      # the subtitled video is encoded, never copied
        self.assertGreater(lit_pixels(out, 1.5), 50)          # first loop
        self.assertGreater(lit_pixels(out, 5.0), 50)          # third loop: the cue stays on the voice's clock, not the clip's
        for quiet in (0.5, 3.0, 7.0): self.assertEqual(lit_pixels(out, quiet), 0, msg=f'second {quiet}')
        self.assertEqual(self.preset_of(out), 'ultrafast')
        self.assertFalse((self.job / merge.OUTPUT).exists())                  # no plain video: the run has one file
        for leftover in (merge.BASE, merge.SUBTITLE_FILE, merge.BURN_OUTPUT + '.tmp'): self.assertFalse((self.job / leftover).exists(), msg=leftover)

    def test_a_logo_is_drawn_on_the_short_clip_once_and_the_subtitles_stay_on_top(self):
        logo = self.root / 'logo.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=white:size=40x40', '-frames:v', '1', str(logo)], check=True)
        voice(self.job / 'voice.vi.wav', 6)
        settings = merge.validate({'files': [black_clip(self.root / 'a.mp4', 2)], 'burn': True, 'ultra': True})
        settings['overlay'] = {'id': 'logo', 'name': 'Logo', 'items': [{'asset': 'logo.png', 'x': 0, 'y': 0, 'width': 0.2, 'opacity': 1}]}
        with patch('audio_translate.video.overlays.pixel_items', return_value=[('logo.png', 10, 10, 40, 1.0)]), \
             patch('audio_translate.video.overlays.picture', return_value=logo), \
             patch.object(merge, '_write_subtitles', write_srt):
            (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings, 'steps': {}}), encoding='utf-8')
            merge.merge(self.job)
        out = self.job / merge.BURN_OUTPUT
        for second in (0.5, 3.0, 5.0): self.assertGreater(lit_pixels(out, second), 1000, msg=f'logo at {second}')   # the logo (1600 px) is on every loop
        self.assertAlmostEqual(float(streams(out)['format']['duration']), 6, delta=0.2)

    def test_clips_that_cover_the_voice_are_one_ffmpeg_command_with_black_bars_kept(self):
        files = [black_clip(self.root / 'wide.mp4', 4, '640x360'), black_clip(self.root / 'tall.mp4', 4, '240x320', 30)]
        job = self.run_ultra(files, 6)
        out = self.job / merge.BURN_OUTPUT
        video = next(s for s in streams(out)['streams'] if s['codec_type'] == 'video')
        self.assertEqual((video['width'], video['height'], video['codec_name']), (640, 360, 'h264'))
        self.assertEqual(job['video_plan']['repeats'], 1)
        self.assertAlmostEqual(float(streams(out)['format']['duration']), 6, delta=0.2)
        self.assertGreater(lit_pixels(out, 1.5), 50); self.assertGreater(lit_pixels(out, 5.0), 50)
        self.assertEqual(lit_pixels(out, 3.0), 0)
        self.assertEqual(self.preset_of(out), 'ultrafast')

    def test_without_the_subtitle_tick_the_copy_stays_a_copy_and_an_encode_is_only_ultrafast(self):
        job = self.run_ultra([clip(self.root / 'a.mp4', 3)], 7, burn=False)
        self.assertEqual(job['video_plan']['mode'], 'copy')
        self.assertTrue((self.job / merge.OUTPUT).is_file()); self.assertFalse((self.job / merge.BURN_OUTPUT).exists())
        self.assertNotEqual(self.preset_of(self.job / merge.OUTPUT), 'ultrafast')    # copied: the source clip's own picture, untouched
        files = [clip(self.root / 'w.mp4', 2, '640x360'), clip(self.root / 'v.mkv', 2, '240x320', 30)]
        job = self.run_ultra(files, 5, burn=False)
        self.assertEqual(job['video_plan']['mode'], 'encode')
        self.assertEqual(self.preset_of(self.job / merge.OUTPUT), 'ultrafast')
        self.assertAlmostEqual(float(streams(self.job / merge.OUTPUT)['format']['duration']), 5, delta=0.2)

    def test_without_ultra_the_merge_is_unchanged(self):
        files = [clip(self.root / 'w.mp4', 2, '640x360'), clip(self.root / 'v.mkv', 2, '240x320', 30)]
        self.run_ultra(files, 5, burn=False, ultra=False)
        self.assertEqual(self.preset_of(self.job / merge.OUTPUT), 'veryfast')

    def test_the_ultra_choice_is_validated_and_makes_the_estimate_faster(self):
        path = clip(self.root / 'a.mp4', 2)
        with self.assertRaises(ValueError): merge.validate({'files': [path], 'ultra': 'yes'})
        self.assertNotIn('ultra', merge.validate({'files': [path]}))
        self.assertTrue(merge.validate({'files': [path], 'ultra': True})['ultra'])
        probed = [merge.probe(path)]
        normal = merge.plan(probed, 'keep', 'high', 600_000, True)
        fast = merge.plan(probed, 'keep', 'high', 600_000, True, ultra=True)
        self.assertAlmostEqual(fast['seconds_per_voice_second'], normal['seconds_per_voice_second'] * merge.ULTRA_FACTOR)
        self.assertEqual(fast['size_bytes'], normal['size_bytes'])            # the bit rate is the chosen quality's, the speed costs no extra size
        self.assertIsNone(merge.plan(probed, 'keep', 'high', 600_000, False, ultra=True)['seconds_per_voice_second'])

    def test_the_run_has_no_burn_step_and_publishes_the_subtitled_video_as_the_merge_result(self):
        from audio_translate.workflow import results
        ultra = {'video': {'files': []}, 'subtitle': {}}
        self.assertEqual(effective_steps({**ultra, 'video': {'files': [], 'burn': True}})[-2:], ['VIDEO', 'BURN'])
        self.assertEqual(effective_steps({**ultra, 'video': {'files': [], 'burn': True, 'ultra': True}})[-2:], ['SUBTITLE', 'VIDEO'])
        self.assertEqual(effective_steps({**ultra, 'video': {'files': [], 'ultra': True}})[-1], 'VIDEO')
        job = {'workflow_no': 0, 'video': {'burn': True, 'ultra': True}}
        files = results.output_files(job)
        self.assertEqual(files['VIDEO'][0][0], 'VIDEO_SUB_MP4'); self.assertNotIn('BURN', files)
        self.assertEqual(results.output_files({'workflow_no': 0, 'video': {'burn': True}})['VIDEO'][0][0], 'VIDEO_MP4')
        self.assertEqual(results.output_files({'workflow_no': 0, 'tool_type': 'video', 'video': {'burn': True, 'ultra': True}})['BURN'][0][0], 'VIDEO_SUB_MP4')


if __name__ == '__main__':
    unittest.main()
