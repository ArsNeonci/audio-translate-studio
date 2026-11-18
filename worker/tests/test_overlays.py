"""Logos and pictures on the video: the picture library, the templates and their defaults, the snapshot a run keeps, and the pixels of a real
merge (video/overlays.py, video/merge.py; docs/OVERLAYS.md)."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from audio_translate.core import storage
from audio_translate.video import merge, overlays
from tests.test_video_merge import FFMPEG, clip, streams, voice

LANDSCAPE = {'width': 320, 'height': 240}
PORTRAIT = {'width': 240, 'height': 320}


def picture(path, color='red', size='200x100', extension='png'):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s={size}', '-frames:v', '1', str(path)], check=True)
    return str(path)


def frame(path, at=0.2):
    """The picture of the video at `at` seconds as (width, height, rgb bytes)."""
    info = next(s for s in streams(path)['streams'] if s['codec_type'] == 'video')
    out = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(at), '-i', str(path), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True)
    return info['width'], info['height'], out.stdout


def pixel(shot, x, y):
    w, _, data = shot
    return tuple(data[(y * w + x) * 3:(y * w + x) * 3 + 3])


@unittest.skipUnless(FFMPEG, 'ffmpeg is not on PATH')
class OverlayLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        p = patch.object(storage, 'DATA', self.root / 'data'); p.start(); self.addCleanup(p.stop)

    def asset(self, name='logo.png', **kwargs):
        return overlays.import_asset(picture(self.root / name, **kwargs), name)

    def test_a_picture_becomes_a_png_in_the_library_and_the_same_picture_is_kept_once(self):
        first = self.asset()
        again = self.asset()
        self.assertEqual((first['id'], first['width'], first['height']), (again['id'], 200, 100))
        self.assertEqual(len(overlays.listing()['assets']), 1)
        self.assertTrue(overlays.asset_path(first['id']).is_file())

    def test_other_picture_types_are_converted_and_a_wrong_type_or_a_broken_file_is_refused(self):
        jpg = self.root / 'photo.jpg'; picture(jpg, 'blue', '64x64')
        self.assertEqual(overlays.import_asset(jpg, 'photo.jpg')['width'], 64)
        with self.assertRaises(overlays.OverlayError) as caught: overlays.import_asset(jpg, 'photo.svg')
        self.assertEqual(caught.exception.code, 'OVERLAY_TYPE')
        broken = self.root / 'broken.png'; broken.write_bytes(b'not a picture at all')
        with self.assertRaises(overlays.OverlayError) as caught: overlays.import_asset(broken, 'broken.png')
        self.assertEqual(caught.exception.code, 'OVERLAY_UNREADABLE')

    def test_a_picture_over_ten_megabytes_is_refused(self):
        big = self.root / 'big.png'; big.write_bytes(b'0' * (overlays.MAX_BYTES + 1))
        with self.assertRaises(overlays.OverlayError) as caught: overlays.import_asset(big, 'big.png')
        self.assertEqual(caught.exception.code, 'OVERLAY_TOO_BIG')

    def test_a_template_is_validated_saved_replaced_and_deleted(self):
        asset = self.asset()
        item = {'asset': asset['id'], 'x': 0.05, 'y': 0.05, 'w': 0.2, 'opacity': 0.8}
        template = overlays.save_template({'name': ' Kênh A ', 'orientation': 'landscape', 'items': [item]})
        self.assertEqual((template['name'], len(template['items'])), ('Kênh A', 1))
        for bad in ({**item, 'x': 0.9, 'w': 0.2}, {**item, 'w': 0}, {**item, 'opacity': 0}, {**item, 'asset': 'f' * 32}, {**item, 'y': True}):
            with self.assertRaises(overlays.OverlayError): overlays.save_template({'name': 'x', 'orientation': 'landscape', 'items': [bad]})
        with self.assertRaises(overlays.OverlayError): overlays.save_template({'name': 'x', 'orientation': 'square', 'items': []})
        with self.assertRaises(overlays.OverlayError) as caught: overlays.save_template({'name': 'kênh a', 'orientation': 'landscape', 'items': []})
        self.assertEqual(caught.exception.code, 'OVERLAY_NAME_TAKEN')
        changed = overlays.save_template({'id': template['id'], 'name': 'Kênh A', 'orientation': 'landscape', 'items': []})
        self.assertEqual((changed['id'], changed['items']), (template['id'], []))
        overlays.delete_template(template['id'])
        self.assertEqual(overlays.listing()['templates'], [])

    def test_a_picture_that_a_template_uses_cannot_be_deleted(self):
        asset = self.asset()
        template = overlays.save_template({'name': 'A', 'orientation': 'landscape', 'items': [{'asset': asset['id'], 'x': 0, 'y': 0, 'w': 0.2}]})
        with self.assertRaises(overlays.OverlayError) as caught: overlays.delete_asset(asset['id'])
        self.assertEqual(caught.exception.code, 'OVERLAY_IN_USE')
        overlays.delete_template(template['id'])
        overlays.delete_asset(asset['id'])
        self.assertFalse(overlays.asset_path(asset['id']).exists())

    def test_each_orientation_has_its_own_default_and_deleting_a_template_clears_it(self):
        land = overlays.save_template({'name': 'Ngang', 'orientation': 'landscape', 'items': []})
        port = overlays.save_template({'name': 'Dọc', 'orientation': 'portrait', 'items': []})
        overlays.set_default('landscape', land['id']); overlays.set_default('portrait', port['id'])
        self.assertEqual(overlays.listing()['defaults'], {'landscape': land['id'], 'portrait': port['id']})
        with self.assertRaises(overlays.OverlayError): overlays.set_default('portrait', land['id'])
        overlays.delete_template(land['id'])
        self.assertEqual(overlays.listing()['defaults'], {'portrait': port['id']})

    def test_a_run_gets_the_default_of_its_first_clip_or_the_template_named_or_none(self):
        asset = self.asset()
        item = {'asset': asset['id'], 'x': 0, 'y': 0, 'w': 0.2}
        land = overlays.save_template({'name': 'Ngang', 'orientation': 'landscape', 'items': [item]})
        port = overlays.save_template({'name': 'Dọc', 'orientation': 'portrait', 'items': [item]})
        overlays.set_default('landscape', land['id']); overlays.set_default('portrait', port['id'])
        self.assertEqual(overlays.resolve('default', [LANDSCAPE])['id'], land['id'])
        self.assertEqual(overlays.resolve(None, [PORTRAIT])['id'], port['id'])
        self.assertIsNone(overlays.resolve('none', [LANDSCAPE]))
        self.assertEqual(overlays.resolve(port['id'], [LANDSCAPE])['id'], port['id'])
        with self.assertRaises(overlays.OverlayError): overlays.resolve('0' * 12, [LANDSCAPE])
        # A run keeps its snapshot even when the template is deleted later.
        snapshot = overlays.resolve(land['id'], [LANDSCAPE])
        overlays.delete_template(land['id'])
        self.assertEqual(overlays.resolve(land['id'], [LANDSCAPE], snapshot), snapshot)
        self.assertIsNone(overlays.resolve('default', [LANDSCAPE]))          # no default any more


@unittest.skipUnless(FFMPEG, 'ffmpeg is not on PATH')
class OverlayMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = self.root / 'job'; (self.job / 'working').mkdir(parents=True)
        self.results = self.root / 'results'; self.results.mkdir()
        for target in ('audio_translate.core.license_gate.assert_allowed',):
            p = patch(target, return_value=True); p.start(); self.addCleanup(p.stop)
        p = patch('audio_translate.workflow.results.destination', return_value=self.results); p.start(); self.addCleanup(p.stop)
        p = patch.object(storage, 'DATA', self.root / 'data'); p.start(); self.addCleanup(p.stop)

    def merged(self, items, size='320x240', seconds=2, **kwargs):
        logo = overlays.import_asset(picture(self.root / 'logo.png', **kwargs), 'logo.png')
        self.count = getattr(self, 'count', 0) + 1
        template = overlays.save_template({'name': f'T{self.count}', 'orientation': 'landscape', 'items': [{'asset': logo['id'], **item} for item in items]}) if items else None
        settings = merge.validate({'files': [{'path': clip(self.root / 'a.mp4', 3, size=size)}], 'resolution': 'keep', 'quality': 'high', 'overlay': template['id'] if template else 'none'})
        overlays.materialize(self.job, settings.get('overlay'))
        voice(self.job / 'voice.vi.wav', seconds)
        (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings, 'steps': {}}), encoding='utf-8')
        merge.merge(self.job)
        return frame(self.job / merge.OUTPUT), json.loads((self.job / 'job.json').read_text(encoding='utf-8'))

    def test_the_picture_lands_where_the_template_puts_it_and_the_merge_encodes(self):
        shot, job = self.merged([{'x': 0.0, 'y': 0.0, 'w': 0.25, 'opacity': 1}])
        self.assertEqual(job['video_plan']['mode'], 'encode')               # copying cannot draw
        r, g, b = pixel(shot, 10, 10)
        self.assertTrue(r > 200 and g < 60 and b < 60, (r, g, b))           # the red logo (80 px wide, 40 px high) covers the corner
        far = pixel(shot, 300, 220)
        self.assertFalse(far[0] > 200 and far[1] < 60 and far[2] < 60, far)  # and nothing else is red

    def test_the_position_follows_the_fractions_and_the_size_the_width(self):
        shot, _ = self.merged([{'x': 0.5, 'y': 0.5, 'w': 0.5, 'opacity': 1}])
        plain, _ = self.merged([])                                          # the same clip without a logo
        inside, outside = pixel(shot, 240, 140), pixel(shot, 100, 60)
        self.assertTrue(inside[0] > 200 and inside[1] < 60 and inside[2] < 60, inside)      # 160 x 80 at (160, 120)
        self.assertLess(max(abs(a - b) for a, b in zip(outside, pixel(plain, 100, 60))), 40)   # untouched away from it

    def test_the_opacity_lets_the_video_show_through(self):
        full, _ = self.merged([{'x': 0.0, 'y': 0.0, 'w': 0.5, 'opacity': 1}], color='white')
        half, _ = self.merged([{'x': 0.0, 'y': 0.0, 'w': 0.5, 'opacity': 0.4}], color='white')
        plain, _ = self.merged([])
        self.assertGreater(min(pixel(full, 20, 20)), 235)                                   # a white logo is white
        self.assertLess(min(pixel(half, 20, 20)), 235)
        self.assertGreater(max(abs(a - b) for a, b in zip(pixel(half, 20, 20), pixel(plain, 20, 20))), 20)   # but the video still shows through

    def test_a_run_without_a_template_still_copies_the_picture(self):
        settings = merge.validate({'files': [{'path': clip(self.root / 'b.mp4', 3)}], 'overlay': 'none'})
        self.assertNotIn('overlay', settings)
        voice(self.job / 'voice.vi.wav', 2)
        (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings, 'steps': {}}), encoding='utf-8')
        merge.merge(self.job)
        self.assertEqual(json.loads((self.job / 'job.json').read_text(encoding='utf-8'))['video_plan']['mode'], 'copy')

    def test_the_run_uses_its_own_copy_of_the_pictures(self):
        logo = overlays.import_asset(picture(self.root / 'logo.png'), 'logo.png')
        template = overlays.save_template({'name': 'T', 'orientation': 'landscape', 'items': [{'asset': logo['id'], 'x': 0, 'y': 0, 'w': 0.3}]})
        settings = merge.validate({'files': [{'path': clip(self.root / 'a.mp4', 3)}], 'overlay': template['id']})
        overlays.materialize(self.job, settings['overlay'])
        overlays.delete_template(template['id']); overlays.delete_asset(logo['id'])      # the library forgets it
        voice(self.job / 'voice.vi.wav', 2)
        (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings, 'steps': {}}), encoding='utf-8')
        merge.merge(self.job)
        self.assertGreater(pixel(frame(self.job / merge.OUTPUT), 10, 10)[0], 200)

    def test_a_missing_picture_is_a_clear_error(self):
        logo = overlays.import_asset(picture(self.root / 'logo.png'), 'logo.png')
        template = overlays.save_template({'name': 'T', 'orientation': 'landscape', 'items': [{'asset': logo['id'], 'x': 0, 'y': 0, 'w': 0.3}]})
        settings = merge.validate({'files': [{'path': clip(self.root / 'a.mp4', 3)}], 'overlay': template['id']})
        overlays.delete_template(template['id']); overlays.delete_asset(logo['id'])      # never copied into the run
        voice(self.job / 'voice.vi.wav', 2)
        (self.job / 'job.json').write_text(json.dumps({'id': 'x', 'video': settings, 'steps': {}}), encoding='utf-8')
        with self.assertRaises(merge.VideoError) as caught: merge.merge(self.job)
        self.assertEqual(caught.exception.code, 'OVERLAY_MISSING')

    def test_the_estimate_knows_a_template_forces_the_encode(self):
        logo = overlays.import_asset(picture(self.root / 'logo.png'), 'logo.png')
        template = overlays.save_template({'name': 'T', 'orientation': 'landscape', 'items': [{'asset': logo['id'], 'x': 0, 'y': 0, 'w': 0.3}]})
        from audio_translate.api import routes_video
        path = clip(self.root / 'a.mp4', 3)
        with patch.object(routes_video, 'voice_length', return_value=5000):
            self.assertEqual(routes_video.estimate([path], 'keep', 'high', None)['plan']['mode'], 'copy')
            self.assertEqual(routes_video.estimate([path], 'keep', 'high', None, False, template['id'])['plan']['mode'], 'encode')


if __name__ == '__main__':
    unittest.main()
