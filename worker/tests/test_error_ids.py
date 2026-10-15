"""Error IDs: every failure shows a Vietnamese sentence, what to do and a short ID; the raw detail stays in the run's log."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from audio_translate.core import error_ids
from audio_translate.core.error_ids import AppError, CODE_IDS, ERRORS
from audio_translate.core.errors import GUIDES, classify, identify, initial_steps, record_failure
from audio_translate.core.storage import read_json, atomic_json

# What a person must never read on the screen: tools and providers, paths, settings names, commands, English.
FORBIDDEN = re.compile(r'ffmpeg|ffprobe|yt-?dlp|libx264|libass|cuda|pytorch|llama|python|\.venv|\.env|results_root|pip |sha-?256|dpapi|vault|lease|'
                       r'gateway|cookie|netscape|http|traceback|exception|hy-?mt|vieneu|funasr|whisper|gemini|json|vram|\\\\|/data|retry|settings|workflow|token|admin',
                       re.I)
ENGLISH_WORDS = re.compile(r'\b(the|could|failed|error|please|not|cannot|invalid|download|upload)\b', re.I)


class ErrorIdTests(unittest.TestCase):
    def test_ids_have_a_stable_shape_and_every_code_points_to_one(self):
        for error_id in ERRORS: self.assertRegex(error_id, r'^[GTCDKVPHMSUX]\d{3}$', error_id)
        for code, error_id in CODE_IDS.items(): self.assertIn(error_id, ERRORS, code)
        self.assertEqual(len(set(CODE_IDS.values())), len(CODE_IDS))                      # one code, one ID

    def test_nothing_shown_to_a_person_names_a_tool_a_path_a_setting_or_uses_english(self):
        for error_id, (what, todo) in ERRORS.items():
            for text in (what, todo):
                self.assertFalse(FORBIDDEN.search(text), f'{error_id}: {text}')
                self.assertFalse(ENGLISH_WORDS.search(text), f'{error_id}: {text}')
                self.assertTrue(text.endswith(('.', ')')), f'{error_id}: {text}')
            self.assertTrue(error_ids.message(error_id).endswith(f'Mã lỗi: {error_id}.'))

    def test_the_old_fix_guides_are_the_same_sentences_without_paths_or_commands(self):
        for code in GUIDES:
            cause, config, steps, commands = GUIDES[code]
            self.assertEqual((config, commands), ('', []), code)
            self.assertFalse(FORBIDDEN.search(cause + ' '.join(steps)), code)

    def test_a_typed_error_keeps_its_id_and_an_unknown_one_is_x900(self):
        self.assertEqual(identify(AppError('T102', 'the page needs to be reloaded')), 'T102')
        self.assertEqual(identify(PermissionError('denied')), 'S102')
        self.assertEqual(identify(OSError(28, 'No space left on device')), 'S101')
        self.assertEqual(identify(RuntimeError('some English text from a library')), 'X900')
        self.assertEqual(identify(AppError('Z999')), 'X900')                                # an ID nobody listed is never shown as is
        self.assertEqual(classify(AppError('T101')), 'YOUTUBE_AUTH')                        # the old code keeps working

    def test_a_failure_shows_the_sentence_and_id_and_keeps_the_raw_text_in_the_log(self):
        with tempfile.TemporaryDirectory() as folder:
            job_dir = Path(folder); (job_dir / 'working').mkdir()
            atomic_json(job_dir / 'job.json', {'id': 'x', 'steps': initial_steps({}), 'status': 'RUNNING'})
            raw = 'ERROR: [youtube] abc: The page needs to be reloaded. HTTP Error 403 C:\\Users\\someone\\notes.txt'
            failure = record_failure(job_dir, 'DOWNLOAD', AppError('T102', raw))
            job = read_json(job_dir / 'job.json')
            self.assertEqual((failure['error_id'], job['status']), ('T102', 'FAILED'))
            for shown in (job['error'], job['steps']['DOWNLOAD']['error']['error_message']):
                self.assertTrue(shown.startswith('YouTube yêu cầu đăng nhập lại.') and shown.endswith('Mã lỗi: T102.'), shown)
                self.assertNotIn('reloaded', shown); self.assertNotIn('403', shown); self.assertNotIn('someone', shown)
            logged = json.loads((job_dir / 'errors.jsonl').read_text(encoding='utf-8').splitlines()[-1])
            self.assertEqual(logged['id'] if 'id' in logged else logged['error_id'], 'T102')
            self.assertIn('reloaded', logged['detail'])                                    # the owner still gets the original text
            unknown = record_failure(job_dir, 'TRANSLATION', RuntimeError('Traceback: something English'))
            self.assertEqual(unknown['error_id'], 'X900')
            self.assertNotIn('Traceback', read_json(job_dir / 'job.json')['error'])


if __name__ == '__main__':
    unittest.main()
