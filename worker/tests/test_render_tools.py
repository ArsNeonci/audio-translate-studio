"""Tools 8 (the person's subtitle file drawn into their video) and 9 (a logo template laid on their video): the subtitle file reader, the RENDER step on
real clips made with ffmpeg, and what the run publishes (docs/RENDER_TOOLS.md)."""
import codecs
import json
import unicodedata
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch
import uuid

from audio_translate.core import storage
from audio_translate.core.storage import read_json
from audio_translate.video import merge, overlays, subtitle_import as si
from audio_translate.workflow import manage, results
from audio_translate.workflow.orchestrator import run
from tests import test_management
from tests.test_overlays import frame, picture, pixel
from tests.test_video_merge import FFMPEG, clip, streams

REAL_RUN = subprocess.run   # the stage process is faked below; the ffprobe and ffmpeg inside the step must still run
SRT = '1\n00:00:00,500 --> 00:00:02,500\nXin chào các bạn\n\n2\n00:00:03,000 --> 00:00:04,000\nHẹn gặp lại\n'


class SubtitleReaderTests(unittest.TestCase):
    def test_srt_vtt_and_the_encodings_such_files_come_in(self):
        for raw, encoding in ((SRT.encode('utf-8'), 'utf-8'), (codecs.BOM_UTF8 + SRT.encode('utf-8'), 'utf-8-sig'), (SRT.encode('utf-16'), 'utf-16'),
                              (unicodedata.normalize('NFD', SRT.replace('Hẹn gặp lại', 'Hẹn lại')).replace('\n', '\r\n').encode('cp1258'), 'cp1258')):   # cp1258 spells letters with combining accents
            text, found = si.decode(raw)
            cues, dropped = si.parse(text)
            self.assertEqual((found, len(cues), dropped, cues[0][2]), (encoding, 2, 0, 'Xin chào các bạn'), encoding)
        self.assertEqual(si.decode(SRT.encode('utf-16-le'))[1], 'utf-16')       # no byte-order mark

    def test_webvtt_short_times_settings_and_tags(self):
        cues, dropped = si.parse('WEBVTT\n\nNOTE a note\n\n00:01.000 --> 00:02.500 align:start\n<c.yellow>Xin</c> <i>chào</i>\n\n1:00:01.000 --> 1:00:02.000\nMột giờ\n')
        self.assertEqual((cues, dropped), ([(1000, 2500, 'Xin chào'), (3601000, 3602000, 'Một giờ')], 0))

    def test_broken_cues_are_dropped_and_counted_and_the_rest_is_sorted(self):
        cues, dropped = si.parse('2\n00:00:05,000 --> 00:00:06,000\nSau\n\n1\n00:00:01,000 --> 00:00:00,500\nNgược\n\n3\n00:00:02,000 --> 00:00:03,000\n\n\n4\nkhông có giờ\n\n5\n00:00:00,000 --> 00:00:01,000\nĐầu\n')
        self.assertEqual(([c[2] for c in cues], dropped), (['Đầu', 'Sau'], 3))

    def test_the_clean_file_is_utf8_srt_numbered_from_one_and_the_original_is_left_alone(self):
        folder = Path(self._testMethodName); folder.mkdir(exist_ok=True)
        try:
            source = folder / 'in.vtt'; source.write_bytes(('WEBVTT\n\n00:01.000 --> 00:02.000\nChào\n').encode('utf-16'))
            report = si.prepare(source, 'in.vtt', folder / 'out.srt', video_ms=10000)
            self.assertEqual((folder / 'out.srt').read_text(encoding='utf-8'), '1\n00:00:01,000 --> 00:00:02,000\nChào\n\n')
            self.assertEqual((report['cues'], report['encoding'], report['longer_than_video']), (1, 'utf-16', False))
            self.assertTrue(source.read_bytes().startswith(codecs.BOM_UTF16_LE))
            late = si.prepare(source, 'in.vtt', folder / 'late.srt', video_ms=1500)
            self.assertTrue(late['longer_than_video'] is False and late['beyond_video'] is False)
            self.assertTrue(si.prepare(source, 'in.vtt', folder / 'late.srt', video_ms=500)['beyond_video'])
        finally:
            import shutil; shutil.rmtree(folder, ignore_errors=True)

    def test_refusals(self):
        folder = Path(self._testMethodName); folder.mkdir(exist_ok=True)
        try:
            for name, data, message in (('a.txt', b'x', 'Use an SRT or VTT subtitle file'), ('a.srt', b'', 'Empty upload'), ('a.srt', b'no cues here', 'The subtitle file has no usable subtitles'),
                                        ('a.srt', b'x' * (si.MAX_BYTES + 1), 'The subtitle file is larger than 5 MB')):
                (folder / name).write_bytes(data)
                with self.assertRaisesRegex(si.SubtitleFileError, message): si.prepare(folder / name, name, folder / 'out.srt')
        finally:
            import shutil; shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(FFMPEG, 'ffmpeg is not on PATH')
class RenderToolTests(unittest.TestCase):
    def setUp(self):
        test_management.ManagementTests.setUp(self)
        p = patch.object(storage, 'DATA', self.data); p.start(); self.addCleanup(p.stop)
        self.root = Path(self.temp.name)
        self.clip = clip(self.root / 'a.mp4', 5)

    def upload(self, text=SRT, name='sub.srt'):
        path = self.data / 'uploads' / f'{uuid.uuid4()}.upload'; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(text.encode('utf-8'))
        return str(path), name

    def video(self, path=None, **extra): return {'files': [{'path': path or self.clip}], 'resolution': 'keep', 'quality': 'high', **extra}

    def render(self, d):
        def execute(command, **kwargs):
            if '--stage' not in command: return REAL_RUN(command, **kwargs)     # the ffprobe and ffmpeg inside the step still run for real
            if command[-1] != 'render': raise AssertionError('Unexpected stage ' + command[-1])
            merge.render(d); return Mock(returncode=0)
        with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=execute): return run(d)

    def logo(self, **item):
        asset = overlays.import_asset(picture(self.root / 'logo.png', 'red', '200x100'), 'logo.png')
        return overlays.save_template({'name': 'T', 'orientation': 'landscape', 'items': [{'asset': asset['id'], 'x': 0, 'y': 0, 'w': 0.25, 'opacity': 1, **item}]})

    def test_tool_8_draws_the_subtitles_keeps_the_sound_and_publishes_one_video(self):
        upload, name = self.upload()
        job = manage.create(tool='subtitle_burn', upload=upload, input_name=name, video=self.video())
        d = results.workspace(job['id']); saved = read_json(d / 'job.json')
        self.assertEqual((saved['tool_steps'], saved['name'], saved['render']['subtitle'], saved['render']['subtitle_report']['cues']), (['RENDER'], 'a.mp4', True, 2))
        self.assertEqual(self.render(d), 0)
        self.assertEqual((read_json(d / 'job.json')['status'], read_json(d / 'job.json')['steps']['RENDER']['state']), ('COMPLETED', 'COMPLETED'))
        out = results.destination(d.name)
        entry = next(f for f in read_json(out / 'outputs.json')['files'] if f['type'] == 'VIDEO_MP4')
        self.assertEqual((entry['step'], entry['path'], entry['status']), ('RENDER', 'video/000001-video.mp4', 'AVAILABLE'))
        info = streams(out / entry['path'])
        kinds = {s['codec_type']: s for s in info['streams']}
        self.assertEqual((kinds['video']['width'], kinds['video']['height'], kinds['audio']['codec_name']), (320, 240, 'aac'))
        self.assertAlmostEqual(float(info['format']['duration']), 5, delta=0.3)
        # The text is on the picture while a cue shows, and not when none does.
        # Against the same moment of the original clip: much of the bottom of the picture changes where the text is drawn, almost none where no cue shows.
        def changed(at):
            import numpy as np
            made, original = (np.frombuffer(frame(path, at)[2], dtype=np.uint8).reshape(240, 320, 3).astype(int)[190:235] for path in (out / entry['path'], self.clip))
            return int((np.abs(made - original).max(axis=2) > 90).sum())
        self.assertGreater(changed(1.0), changed(2.8) + 60)

    def test_tool_8_can_lay_a_logo_in_the_same_pass(self):
        template = self.logo()
        upload, name = self.upload()
        job = manage.create(tool='subtitle_burn', upload=upload, input_name=name, video=self.video(overlay=template['id']))
        d = results.workspace(job['id']); self.assertEqual(self.render(d), 0)
        shot = frame(next((results.destination(d.name) / 'video').glob('*.mp4')), 1.0)
        r, g, b = pixel(shot, 10, 10)
        self.assertTrue(r > 200 and g < 60 and b < 60, (r, g, b))

    def test_tool_9_lays_the_logo_and_needs_a_template(self):
        with self.assertRaisesRegex(ValueError, 'Choose a logo template'): manage.create(tool='overlay', video=self.video())      # no default, none chosen
        template = self.logo()
        job = manage.create(tool='overlay', video=self.video(overlay=template['id']))
        d = results.workspace(job['id']); saved = read_json(d / 'job.json')
        self.assertEqual((saved['render']['subtitle'], saved['render']['overlay']['id']), (False, template['id']))
        self.assertEqual(self.render(d), 0)
        out = results.destination(d.name)
        self.assertGreater(pixel(frame(next((out / 'video').glob('*.mp4')), 1.0), 10, 10)[0], 200)
        self.assertEqual(read_json(d / 'job.json')['video_plan']['mode'], 'encode')

    def test_tool_9_takes_the_default_template_of_the_videos_orientation(self):
        template = self.logo(); overlays.set_default('landscape', template['id'])
        job = manage.create(tool='overlay', video=self.video())
        self.assertEqual(read_json(results.workspace(job['id']) / 'job.json')['render']['overlay']['id'], template['id'])

    def test_one_video_only_and_a_subtitle_file_for_tool_8(self):
        upload, name = self.upload()
        with self.assertRaisesRegex(ValueError, 'Choose one video'):
            manage.create(tool='subtitle_burn', upload=upload, input_name=name, video={'files': [{'path': self.clip}, {'path': self.clip}]})
        with self.assertRaisesRegex(ValueError, 'Choose a subtitle file'): manage.create(tool='subtitle_burn', video=self.video())
        with self.assertRaisesRegex(ValueError, 'Use an SRT or VTT'): manage.create(tool='subtitle_burn', upload=upload, input_name='sub.txt', video=self.video())
        with self.assertRaisesRegex(ValueError, 'Tool 9 takes no file'): manage.create(tool='overlay', upload=upload, input_name=name, video=self.video(overlay=self.logo()['id']))
        self.assertEqual(list((self.data / 'tool-tmp').iterdir()), [])         # a refused run leaves nothing behind

    def test_a_video_that_was_moved_gives_the_video_missing_error(self):
        upload, name = self.upload()
        job = manage.create(tool='subtitle_burn', upload=upload, input_name=name, video=self.video())
        d = results.workspace(job['id']); Path(self.clip).rename(self.root / 'moved.mp4')
        self.assertEqual(self.render(d), 1)
        error = read_json(d / 'job.json')['steps']['RENDER']['error']
        self.assertEqual((error['error_code'], error['error_id']), ('VIDEO_MISSING', 'H101'))

    def test_sound_that_an_mp4_cannot_hold_is_encoded_and_a_silent_video_stays_silent(self):
        mkv = self.root / 'v.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=duration=3:size=320x240:rate=25', '-f', 'lavfi', '-i', 'sine=duration=3', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-c:a', 'libvorbis', str(mkv)], check=True)
        silent = self.root / 's.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=duration=3:size=320x240:rate=25', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(silent)], check=True)
        for source, expected in ((mkv, 'aac'), (silent, None)):
            upload, name = self.upload()
            job = manage.create(tool='subtitle_burn', upload=upload, input_name=name, video=self.video(str(source)))
            d = results.workspace(job['id']); self.assertEqual(self.render(d), 0)
            found = [s['codec_name'] for s in streams(next((results.destination(d.name) / 'video').glob('*.mp4')))['streams'] if s['codec_type'] == 'audio']
            self.assertEqual(found, [expected] if expected else [])

    def test_the_estimate_follows_the_length_of_the_video(self):
        from audio_translate.api import routes_video
        plan = routes_video.render_estimate(self.clip, 'keep', 'high', True, None)
        self.assertEqual((plan['plan']['mode'], plan['plan']['seconds_per_second'] > 0, plan['enough']), ('encode', True, True))
        self.assertIn('error', routes_video.render_estimate(str(self.root / 'none.mp4'), 'keep', 'high', True, None))

    def test_a_tool_run_publishes_its_video_without_touching_the_workflow_file_names(self):
        self.assertEqual([k for k, _, _ in results.output_files({'tool_type': 'overlay'})['RENDER']], ['VIDEO_MP4'])
        flow = results.output_files({})
        self.assertNotIn('RENDER', flow)
        self.assertEqual(dict((k, r) for k, _, r in flow['VIDEO'])['VIDEO_MP4'], 'video/video.vi.mp4')


if __name__ == '__main__':
    unittest.main()
