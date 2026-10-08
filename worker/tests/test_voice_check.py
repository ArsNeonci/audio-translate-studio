"""The check before the voice step: Chinese/Japanese/Korean characters never reach the voice."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_translate.core.storage import atomic_json
from audio_translate.tts.adapters import adapter_settings
from audio_translate.tts.voice_check import clean_foreign, strip_foreign
from audio_translate.workflow.postprocess import synthesize
from tests.test_postprocess import FakeTTS


def rows_of(path): return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


class VoiceCheckTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('audio_translate.core.license_gate.assert_allowed', return_value=True); patcher.start(); self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name) / 'job'; (self.job / 'working').mkdir(parents=True)
        atomic_json(self.job / 'job.json', {'status': 'MODERATION_COMPLETED', 'workflow_version': 2})
        self.path = self.job / 'transcript.vi.moderated.jsonl'

    def write(self, texts):
        self.path.write_text(''.join(json.dumps({'start_ms': i * 1000, 'end_ms': i * 1000 + 900, 'text_vi_moderated': t}, ensure_ascii=False) + '\n' for i, t in enumerate(texts)),
                             encoding='utf-8', newline='\n')

    def test_strips_han_kana_and_hangul_and_keeps_vietnamese(self):
        self.assertEqual(strip_foreign('Anh ấy tên là 李明 và nói xin chào.'), 'Anh ấy tên là và nói xin chào.')
        self.assertEqual(strip_foreign('こんにちは Chào 안녕 bạn'), 'Chào bạn')
        self.assertEqual(strip_foreign('Lý Minh (李明) đến, 他 cười.'), 'Lý Minh đến, cười.')
        self.assertEqual(strip_foreign('Xin chào 世界.'), 'Xin chào.')
        self.assertEqual(strip_foreign('Chỉ có tiếng Việt, đủ dấu: ắ ằ ẳ ẵ ặ.'), 'Chỉ có tiếng Việt, đủ dấu: ắ ằ ẳ ẵ ặ.')

    def test_a_row_with_nothing_left_becomes_a_pause_not_an_empty_unit(self):
        self.assertEqual(strip_foreign('你好世界'), '…')

    def test_only_rows_with_foreign_text_change_and_a_report_is_left(self):
        self.write(['Xin chào.', 'Hắn gọi 老王 đến.', 'Không có gì.', '再见'])
        before = self.path.read_text(encoding='utf-8').splitlines()
        report = clean_foreign(self.job)
        self.assertEqual((report['rows_checked'], report['rows_changed'], report['characters_removed'], report['rows']), (4, 2, 4, [1, 3]))
        after = self.path.read_text(encoding='utf-8').splitlines()
        self.assertEqual((after[0], after[2]), (before[0], before[2]))        # untouched rows are byte-identical
        rows = rows_of(self.path)
        self.assertEqual((rows[1]['text_vi_moderated'], rows[3]['text_vi_moderated']), ('Hắn gọi đến.', '…'))
        self.assertEqual(rows[1]['start_ms'], 1000)                           # timing and other fields survive
        self.assertEqual(json.loads((self.job / 'working' / 'voice-check.json').read_text(encoding='utf-8'))['rows_changed'], 2)

    def test_clean_text_is_never_rewritten_and_a_second_run_changes_nothing(self):
        self.write(['Xin chào.', 'Tạm biệt.'])
        before = self.path.read_bytes()
        self.assertEqual(clean_foreign(self.job)['rows_changed'], 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.job / 'working' / 'voice-check.json').exists())
        self.write(['Có 字 ở đây.']); clean_foreign(self.job); cleaned = self.path.read_bytes()
        self.assertEqual(clean_foreign(self.job)['rows_changed'], 0); self.assertEqual(self.path.read_bytes(), cleaned)

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(clean_foreign(self.job)['rows_checked'], 0)

    def test_the_voice_step_receives_the_cleaned_text(self):
        self.write(['Xin chào 世界.', 'Tạm biệt.'])
        adapter_settings(self.job)
        tts = FakeTTS()
        synthesize(self.job, tts)
        self.assertEqual(tts.calls, ['Xin chào.', 'Tạm biệt.'])
        self.assertTrue(all('世' not in c and '界' not in c for c in tts.calls))


if __name__ == '__main__':
    unittest.main()
