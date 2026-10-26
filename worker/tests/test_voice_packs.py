import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from audio_translate.core.storage import read_json
from audio_translate.tts import adapters, voice_packs as packs, voices


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class VoicePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # A base "onnx_update" folder whose shared data file holds two fp32 matrices after a small header.
        self.base = self.root/'base'; self.base.mkdir()
        for name in packs.BASE_FILES: (self.base/name).write_bytes(b'graph ' + name.encode())
        self.first, self.second = np.arange(6, dtype=np.float32).reshape(2, 3), np.ones((3, 2), dtype=np.float32)
        (self.base/packs.DATA_FILE).write_bytes(b'\x07' * 16 + self.first.tobytes() + self.second.tobytes())
        self.left = [np.full((2, 1), 0.5, np.float32), np.arange(3, dtype=np.float32).reshape(3, 1)]
        self.right = [np.ones((1, 3), np.float32), np.full((1, 2), 2.0, np.float32)]
        self.pack = self.make_pack('Thùy Dương', 'thuy-duong')
        for module, name, value in [(packs, 'PACKS', self.root/'packs'), (packs, 'DATA', self.root/'data')]:
            mock = patch.object(module, name, value); mock.start(); self.addCleanup(mock.stop)
        mock = patch.object(packs, 'base_folder', return_value=self.base); self.base_folder = mock.start(); self.addCleanup(mock.stop)

    def make_pack(self, voice, slug, **overrides):
        folder = self.root/'packs'/slug; folder.mkdir(parents=True)
        np.savez(folder/'delta.npz', offsets=np.array([16, 16 + 24]), shapes=np.array([[2, 3], [3, 2]]),
                 left_0=self.left[0], right_0=self.right[0], left_1=self.left[1], right_1=self.right[1])
        record = {'format': packs.FORMAT, 'id': voice, 'description': 'Nữ · Bắc · Phong cách tự nhiên', 'gender': 'female',
                  'region': 'Bắc', 'style': 'tu_nhien', 'aliases': [], 'speaker_emb': [0.1] * 192,
                  'base': {'repo': 'r', 'revision': 'x', 'subfolder': 'onnx_update', 'data_sha256': sha(self.base/packs.DATA_FILE)},
                  'delta': {'file': 'delta.npz', 'sha256': sha(folder/'delta.npz')}, **overrides}
        (folder/'voice.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return folder

    def test_listed_like_a_preset_and_broken_packs_skipped(self):
        self.make_pack('Hỏng', 'broken', speaker_emb=[0.1] * 10)
        found = packs.packs()
        self.assertEqual(list(found), ['Thùy Dương'])
        entry = packs.preset_entry(found['Thùy Dương'])
        self.assertEqual((entry['description'], entry['codes'], entry['pack']), ('Nữ · Bắc · Phong cách tự nhiên', None, 'thuy-duong'))
        self.assertEqual(packs.engine_voice(found['Thùy Dương'])['speaker_emb'].shape, (192,))

    def test_patch_adds_each_update_and_keeps_the_rest(self):
        onnx = packs.prepare(packs.find('Thùy Dương'))
        raw = (onnx/packs.DATA_FILE).read_bytes()
        self.assertEqual(raw[:16], b'\x07' * 16)
        first = np.frombuffer(raw[16:40], np.float32).reshape(2, 3)
        second = np.frombuffer(raw[40:64], np.float32).reshape(3, 2)
        np.testing.assert_allclose(first, self.first + self.left[0] @ self.right[0])
        np.testing.assert_allclose(second, self.second + self.left[1] @ self.right[1])
        for name in packs.BASE_FILES: self.assertEqual((onnx/name).read_bytes(), (self.base/name).read_bytes())
        self.assertEqual((self.base/packs.DATA_FILE).read_bytes()[16:40], self.first.tobytes())   # the shared base is untouched

    def test_built_once_and_rebuilt_when_the_pack_changes(self):
        pack = packs.find('Thùy Dương')
        packs.prepare(pack); packs.prepare(pack)
        self.assertEqual(self.base_folder.call_count, 1)
        changed = {**pack, 'base': {**pack['base'], 'revision': 'y'}}
        packs.prepare(changed)
        self.assertEqual(self.base_folder.call_count, 2)
        self.assertEqual(read_json(packs.DATA/'voice-packs'/'thuy-duong'/'ready.json')['signature'], packs.signature(changed))

    def test_damaged_delta_or_other_base_is_refused(self):
        pack = packs.find('Thùy Dương')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            packs.prepare({**pack, 'base': {**pack['base'], 'data_sha256': '0' * 64}})
        (self.pack/'delta.npz').write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError, 'damaged'):
            packs.prepare(packs.find('Thùy Dương'))
        self.assertFalse((packs.DATA/'voice-packs'/'thuy-duong'/'ready.json').exists())

    def test_waits_while_another_process_builds(self):
        pack = packs.find('Thùy Dương')
        sleeps = []
        with patch.object(packs, 'file_lock', side_effect=packs.LockedError('busy')):
            with self.assertRaises(RuntimeError):
                packs.prepare(pack, timeout=-1, sleep=sleeps.append)
        self.assertEqual(sleeps, [])
        packs.prepare(pack)   # the other process finished: a later call finds the folder ready
        with patch.object(packs, 'file_lock', side_effect=packs.LockedError('busy')):
            self.assertTrue(packs.prepare(pack).is_dir())

    def test_voice_list_includes_the_pack(self):
        presets, _ = voices.live_presets()
        self.assertEqual(presets['Thùy Dương']['pack'], 'thuy-duong')


class FakeVieneu:
    made = []

    def __init__(self, **kwargs):
        self.kwargs, self.sample_rate = kwargs, 48000
        FakeVieneu.made.append(kwargs)

    def get_preset_voice(self, name):
        if name != 'Hải Đăng': raise ValueError(name)

    def infer_stream(self, text, voice, **kwargs):
        self.voice = voice
        yield np.zeros(480, np.float32)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root/'src'/'vieneu').mkdir(parents=True); (root/'src'/'vieneu'/'factory.py').write_text('')
        pack = {'id': 'Thùy Dương', 'speaker_emb': [0.2] * 192, 'delta': {'sha256': 'a'}, 'base': {'revision': 'x'}}
        FakeVieneu.made = []
        mock = patch.dict(sys.modules, {'vieneu': types.SimpleNamespace(Vieneu=FakeVieneu)}); mock.start(); self.addCleanup(mock.stop)
        for name, value in [('find', lambda voice: pack if voice == 'Thùy Dương' else None), ('prepare', lambda p: root/'onnx')]:
            mock = patch.object(packs, name, value); mock.start(); self.addCleanup(mock.stop)
        mock = patch.object(adapters, 'vieneu_source', return_value=root); mock.start(); self.addCleanup(mock.stop)
        mock = patch('audio_translate.tts.voice_styles.finish_audio'); mock.start(); self.addCleanup(mock.stop)
        self.output = root/'out.wav'

    def test_pack_voice_uses_its_patched_model_and_switching_reloads(self):
        adapter = adapters.TTSAdapter({'source': 'x', 'device': 'cpu', 'precision': 'fp32', 'voice': 'Thùy Dương'}, threads=1)
        adapter.synthesize('Xin chào.', self.output)
        self.assertEqual((FakeVieneu.made[-1]['backend'], FakeVieneu.made[-1]['onnx_dir']), ('onnx', str(Path(self.temp.name)/'onnx')))
        self.assertIsNone(adapter.engine.voice['codes'])
        adapter.synthesize('Lần nữa.', self.output)
        self.assertEqual(len(FakeVieneu.made), 1)   # same voice: no reload
        adapter.settings['voice'] = 'Hải Đăng'
        adapter.synthesize('Xin chào.', self.output)
        self.assertEqual(len(FakeVieneu.made), 2)
        self.assertNotIn('onnx_dir', FakeVieneu.made[-1])
        self.assertEqual(adapter.engine.voice, 'Hải Đăng')


if __name__ == '__main__':
    unittest.main()
