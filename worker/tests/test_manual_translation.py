"""Manual translation: the numbered paragraphs, the check of the person's text, a workflow that waits for it, a file loaded at any stage
(Reprocess) and tool 7 that cuts the Chinese text into parts (docs/MANUAL_TRANSLATION.md)."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import uuid

import numpy as np
import soundfile as sf

from audio_translate.core import storage
from audio_translate.core.errors import initial_steps
from audio_translate.core.storage import read_json, update_job
from audio_translate.translation import manual_text as mt
from audio_translate.workflow import imports, manage, results
from audio_translate.workflow.orchestrator import run
from audio_translate.workflow.postprocess import moderate, synthesize, translate
from tests import test_management
from tests.test_postprocess import FakeTranslator, FakeTTS

ROWS = [(0, 1000, '你好。'), (1100, 2000, '再见。'), (6000, 7000, '新的一段。'), (7100, 8000, '结束。')]


def rows(items=ROWS): return [{'start_ms': a, 'end_ms': b, 'text': t} for a, b, t in items]


class ManualTextTests(unittest.TestCase):
    def test_a_pause_over_one_and_a_half_seconds_ends_a_paragraph(self):
        paras = mt.paragraphs(rows())
        self.assertEqual([(p['n'], p['start_ms'], p['end_ms'], p['text']) for p in paras], [(1, 0, 2000, '你好。再见。'), (2, 6000, 8000, '新的一段。结束。')])

    def test_a_long_paragraph_is_closed_at_240_characters_like_the_transcript(self):
        long = [{'start_ms': i * 100, 'end_ms': i * 100 + 90, 'text': '字' * 50} for i in range(10)]
        self.assertEqual([len(p['text']) for p in mt.paragraphs(long)], [250, 250])   # closed once it passes 240

    def test_plain_text_rows_are_one_paragraph_each(self):
        flat = [{'start_ms': i, 'end_ms': i, 'text': t} for i, t in enumerate(['一', '二', '三'])]
        self.assertEqual([p['text'] for p in mt.paragraphs(flat)], ['一', '二', '三'])

    def test_numbered_text_lands_on_its_paragraph_and_chatter_is_dropped(self):
        paras = mt.paragraphs(rows())
        pairs, report = mt.parse_translation('Đây là bản dịch:\n\n[2] Đoạn mới. Hết.\n[1] Xin chào.\nTạm biệt.\n', paras)
        self.assertEqual(report['mode'], 'numbered')
        self.assertEqual(pairs, [(0, 2000, 'Xin chào. Tạm biệt.'), (6000, 8000, 'Đoạn mới. Hết.')])
        self.assertTrue(report['out_of_order'])
        self.assertEqual(report['dropped_lines'], 1)
        self.assertEqual(mt.blocking(report), [])

    def test_missing_unknown_and_empty_numbers_block_the_import(self):
        paras = mt.paragraphs(rows())
        _, report = mt.parse_translation('[1] Xin chào.\n[7] Lạ.\n', paras)
        self.assertEqual((report['missing'], report['unknown']), ([2], [7]))
        self.assertEqual(mt.blocking(report), ['Some paragraphs have no translation', 'Some numbers do not belong to this workflow'])
        _, report = mt.parse_translation('[1] Xin chào.\n[2]\n', paras)
        self.assertEqual(mt.blocking(report), ['Some paragraphs are empty'])

    def test_a_repeated_number_is_reported_and_leftover_chinese_is_counted(self):
        paras = mt.paragraphs(rows())
        _, report = mt.parse_translation('[1] Xin chào 你好.\n[1] Lại.\n[2] Ổn.\n', paras)
        self.assertEqual((report['duplicate'], report['han_paragraphs']), ([1], 1))

    def test_text_without_numbers_matches_by_position_when_the_counts_agree(self):
        paras = mt.paragraphs(rows())
        pairs, report = mt.parse_translation('Xin chào.\n\nĐoạn mới.\n', paras)
        self.assertEqual((report['mode'], report['estimated_time']), ('plain', False))
        self.assertEqual([(a, b) for a, b, _ in pairs], [(0, 2000), (6000, 8000)])

    def test_text_without_numbers_and_another_count_shares_the_time_by_length(self):
        paras = mt.paragraphs(rows())
        pairs, report = mt.parse_translation('Một.\n\nHai.\n\nBa.\n', paras)
        self.assertTrue(report['estimated_time'])
        self.assertEqual((pairs[0][0], pairs[-1][1]), (0, 8000))
        self.assertTrue(all(a <= b for a, b, _ in pairs) and all(pairs[i][1] <= pairs[i + 1][0] for i in range(2)))

    def test_a_long_paragraph_is_cut_at_sentence_ends_and_the_time_is_shared(self):
        out = mt.rows_from_pairs([(0, 3000, 'Một câu. Hai câu rất dài hơn nhiều. Ba!')])
        self.assertEqual([r['text_vi'] for r in out], ['Một câu.', 'Hai câu rất dài hơn nhiều.', 'Ba!'])
        self.assertEqual((out[0]['start_ms'], out[-1]['end_ms']), (0, 3000))
        self.assertTrue(all(out[i]['end_ms'] == out[i + 1]['start_ms'] for i in range(2)))

    def test_parts_never_cut_a_paragraph_and_together_hold_every_paragraph_once(self):
        many = rows([(i * 5000, i * 5000 + 1000, f'第{i}段，' + '字' * 120) for i in range(40)])
        files, paras = mt.split_files(many, 1000, 'Dịch nhé')
        self.assertGreater(len(files), 3)
        texts = ''.join(text for _, text in files)
        for p in paras: self.assertEqual(texts.count(f"[{p['n']}] {p['text']}"), 1)
        for name, text in files:
            self.assertTrue(text.startswith('Dịch nhé'))
            body = text.split('-->')[1]
            self.assertLessEqual(len(body), 1000 + 80)
        self.assertEqual([n for n, _ in files][:2], ['part-001.md', 'part-002.md'])

    def test_a_paragraph_longer_than_the_limit_gets_a_part_of_its_own(self):
        files, _ = mt.split_files(rows([(0, 1, '字' * 700)]), 500, '')
        self.assertEqual(len(files), 1)

    def test_split_limits_are_checked(self):
        for size in (499, 20001, True, '3000'):
            with self.assertRaises(mt.ManualTextError): mt.split_plan([{'n': 1, 'text': '字'}], size)
        self.assertEqual(mt.validate_split(None)['max_chars'], 3000)
        self.assertEqual(mt.validate_split({'prompt_text': '  '})['prompt_text'], mt.DEFAULT_PROMPT)


class ManualWorkflowTests(unittest.TestCase):
    setUp = test_management.ManagementTests.setUp

    def setUp(self):   # noqa: F811  (the management fixture plus the folder the imports use)
        test_management.ManagementTests.setUp(self)
        p = patch.object(storage, 'DATA', self.data); p.start(); self.addCleanup(p.stop)

    def workflow(self, **kwargs):
        job = manage.create('https://youtu.be/1JzKgwOESoM', self.voice, **kwargs)
        return results.workspace(job['id'])

    def transcribed(self, d):
        """What Download and Transcription leave behind."""
        job = read_json(d / 'job.json'); steps = job['steps']
        for s in ('DOWNLOAD', 'TRANSCRIPTION'): steps[s]['state'] = 'COMPLETED'
        update_job(d, steps=steps)
        (d / 'transcript.zh.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows()), encoding='utf-8')
        (d / 'transcript.zh.md').write_text('你好。再见。\n\n新的一段。结束。\n', encoding='utf-8')

    def text_file(self, text, name='vi.md'):
        path = self.data / 'uploads' / f'{uuid.uuid4()}.upload'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return str(path), name

    def stages(self, d, seen):
        def execute(command, **kwargs):
            stage = command[-1]; seen.append(stage)
            if stage == 'translation': translate(d, FakeTranslator())
            elif stage == 'moderation': moderate(d, self.rules)
            elif stage == 'tts': synthesize(d, FakeTTS())
            elif stage == 'subtitle':
                from audio_translate.video.subtitles import run as build
                build(d)
            elif stage == 'split': mt.run_split(d)
            else: raise AssertionError('Unexpected stage ' + stage)
            return Mock(returncode=0)
        return execute

    def go(self, d):
        seen = []
        with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=self.stages(d, seen)): code = run(d)
        return code, seen

    def load(self, d, step, text, name='vi.md', **kwargs):
        upload, name = self.text_file(text, name)
        return imports.prepare(d.name, step, upload, name, 'text/markdown')

    def published(self, d):
        return {f['type']: f for f in read_json(results.destination(d.name) / 'outputs.json')['files']}

    def test_reprocess_switches_a_workflow_to_hand_translation_and_back(self):
        d = self.workflow(); self.transcribed(d)
        code, seen = self.go(d)
        self.assertEqual((code, read_json(d / 'job.json')['status']), (0, 'COMPLETED'))
        manage.reprocess(d.name, 'TRANSLATION', manual=True, address='drama')            # by hand: the parts are cut, then the run waits
        saved = read_json(d / 'job.json')
        self.assertEqual((saved['manual_translation'], saved['selected_address_profile']), (True, None))
        code, seen = self.go(d)
        saved = read_json(d / 'job.json')
        self.assertEqual((code, seen, saved['status']), (0, ['split'], 'COMPLETED'))
        self.assertEqual(self.published(d)['SPLIT_001']['status'], 'AVAILABLE')
        manage.reprocess(d.name, 'TRANSLATION', manual=False)                               # the machine translates again
        self.assertNotIn('manual_translation', read_json(d / 'job.json'))
        code, seen = self.go(d)
        self.assertEqual((code, seen[0], read_json(d / 'job.json')['status']), (0, 'translation', 'COMPLETED'))
        for bad in ({'step': 'MODERATION', 'manual': True}, {'step': 'TTS', 'manual': False}, {'step': 'TRANSLATION', 'manual': 'yes'}):
            with self.assertRaises(ValueError, msg=repr(bad)): manage.reprocess(d.name, bad['step'], manual=bad['manual'])

    # --- the workflow that waits ----------------------------------------------------------------------------------------
    def test_a_manual_workflow_stops_after_the_chinese_text_and_waits(self):
        d = self.workflow(manual=True)
        job = read_json(d / 'job.json')
        self.assertEqual((job['manual_translation'], job['selected_address_profile']), (True, None))
        self.transcribed(d)
        code, seen = self.go(d)
        saved = read_json(d / 'job.json')
        self.assertEqual((code, seen, saved['status'], saved['progress']), (0, ['split'], 'COMPLETED', 100))      # it ENDS here, like tool 7
        self.assertEqual((saved['steps']['SPLIT']['state'], saved['steps']['TRANSLATION']['state']), ('COMPLETED', 'PENDING'))
        files = self.published(d)
        self.assertTrue(files['ZH_MD']['status'] == 'AVAILABLE' and files['SPLIT_001']['status'] == 'AVAILABLE' and files['SPLIT_ZIP']['step'] == 'SPLIT')
        self.assertIsNotNone(saved['completed_at'])

    def test_manual_translation_is_for_workflows_with_no_translation_mode(self):
        with self.assertRaisesRegex(ValueError, 'workflows only'): manage.create(tool='translation', manual=True)
        with self.assertRaisesRegex(ValueError, 'workflows only'): manage.create('https://youtu.be/1JzKgwOESoM', self.voice, manual=True, mode='genius')

    def test_the_translation_loaded_continues_from_moderation_and_keeps_the_timestamps(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        prepared = self.load(d, 'MODERATION', '[1] Xin chào. Tạm biệt.\n[2] Đoạn mới. Hết.\n')
        self.assertEqual(prepared['report']['mode'], 'numbered')
        manage.reprocess(d.name, 'MODERATION', import_id=prepared['import_id'])
        saved = read_json(d / 'job.json')
        self.assertEqual((saved['status'], saved['steps']['TRANSLATION']['state'], saved['steps']['TRANSLATION']['origin']), ('QUEUED', 'COMPLETED', 'import'))
        code, seen = self.go(d)
        self.assertEqual((code, seen), (0, ['moderation', 'tts', 'subtitle']))
        saved = read_json(d / 'job.json')
        self.assertEqual(saved['status'], 'COMPLETED')
        files = self.published(d)
        self.assertEqual((files['VI_JSONL']['status'], files['VI_JSONL']['origin']), ('AVAILABLE', 'import'))
        moderated = [json.loads(l) for l in (d / 'transcript.vi.moderated.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([(r['start_ms'], r['end_ms'], r['text_vi_moderated']) for r in moderated],
                         [(0, 1000, 'Xin chào.'), (1000, 2000, 'Tạm biệt.'), (6000, 7385, 'Đoạn mới.'), (7385, 8000, 'Hết.')])   # time shared by length
        self.assertTrue(files['VOICE_WAV']['status'] == 'AVAILABLE' and files['SUBTITLE_SRT']['status'] == 'AVAILABLE')
        self.assertTrue(saved['manual_translation'] and saved['selected_address_profile'] is None)

    def test_a_manual_workflow_takes_no_video_and_ends_like_tool_7_then_gains_one_when_the_translation_is_loaded(self):
        from audio_translate.workflow.results import output_files
        d = self.workflow(manual=True, video={'files': [{'path': str(self.data / 'x.mp4')}]})       # a video sent by mistake is ignored, not probed
        job = read_json(d / 'job.json')
        self.assertNotIn('video', job); self.assertEqual(manage.effective_steps(job)[-2:], ['TTS', 'SUBTITLE'])
        self.transcribed(d)
        code, seen = self.go(d)
        saved = read_json(d / 'job.json')
        self.assertEqual((code, seen, saved['status']), (0, ['split'], 'COMPLETED'))
        files = self.published(d)                                         # the same products as tool 7: one zip and the numbered parts
        self.assertEqual((files['SPLIT_ZIP']['status'], files['SPLIT_001']['status'], files['SPLIT_ZIP']['path'].endswith('parts.zip')), ('AVAILABLE', 'AVAILABLE', True))
        self.assertNotIn('VIDEO_MP4', files)
        prepared = self.load(d, 'MODERATION', '[1] Xin chào. Tạm biệt.\n[2] Đoạn mới. Hết.\n')       # run ended (not waiting): the load is accepted all the same
        manage.reprocess(d.name, 'MODERATION', import_id=prepared['import_id'])
        self.assertEqual(self.go(d)[1], ['moderation', 'tts', 'subtitle'])
        self.assertEqual(read_json(d / 'job.json')['status'], 'COMPLETED')

    def test_a_translation_with_a_missing_number_is_refused_until_the_missing_part_comes(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        prepared = self.load(d, 'MODERATION', '[1] Xin chào.\n')
        self.assertFalse(prepared['ready'])
        self.assertEqual(prepared['report']['blocked'], ['Some paragraphs have no translation'])
        with self.assertRaisesRegex(ValueError, 'cannot be used yet'): manage.reprocess(d.name, 'MODERATION', import_id=prepared['import_id'])
        # The missing part arrives as a second file: the draft becomes usable.
        upload, name = self.text_file('[2] Đoạn mới.\n', 'part-002.md')
        imports.add_part(d.name, prepared['import_id'], upload, name)
        checked = imports.check(d.name, prepared['import_id'], [1, 2])
        self.assertTrue(checked['ready'])
        self.assertEqual([(p['name'], p['first'], p['last']) for p in checked['report']['parts']], [('vi.md', 1, 1), ('part-002.md', 2, 2)])
        manage.reprocess(d.name, 'MODERATION', import_id=prepared['import_id'])
        self.assertEqual(self.go(d), (0, ['moderation', 'tts', 'subtitle']))

    def test_numbered_parts_land_on_their_paragraphs_in_any_order(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        first = self.load(d, 'MODERATION', '[2] Đoạn mới.\n', 'part-002.md')
        imports.add_part(d.name, first['import_id'], *self.text_file('Đây là bản dịch:\n[1] Xin chào.\n', 'part-001.md'))
        for order in ([1, 2], [2, 1]):
            checked = imports.check(d.name, first['import_id'], order)
            self.assertTrue(checked['ready'], checked['report'])
            rows = (imports.root() / first['import_id'] / 'transcript.vi.jsonl').read_text(encoding='utf-8')
            self.assertLess(rows.index('Xin chào'), rows.index('Đoạn mới'))
        self.assertEqual({p['name']: p['dropped_lines'] for p in checked['report']['parts']}, {'part-001.md': 1, 'part-002.md': 0})

    def test_text_without_numbers_follows_the_order_of_the_files(self):
        d = self.workflow(); self.transcribed(d); update_job(d, status='PAUSED')
        first = self.load(d, 'MODERATION', 'Đoạn hai.\n', 'b.txt')
        imports.add_part(d.name, first['import_id'], *self.text_file('Đoạn một.\n', 'a.txt'))
        checked = imports.check(d.name, first['import_id'], [2, 1])
        rows = (imports.root() / first['import_id'] / 'transcript.vi.jsonl').read_text(encoding='utf-8')
        self.assertTrue(checked['ready'] and rows.index('Đoạn một') < rows.index('Đoạn hai'))
        checked = imports.check(d.name, first['import_id'], [1, 2])
        rows = (imports.root() / first['import_id'] / 'transcript.vi.jsonl').read_text(encoding='utf-8')
        self.assertLess(rows.index('Đoạn hai'), rows.index('Đoạn một'))

    def test_a_part_loaded_twice_mixed_files_and_bad_orders_are_reported(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        first = self.load(d, 'MODERATION', '[1] Xin chào.\n[2] Đoạn mới.\n', 'part-001.md')
        imports.add_part(d.name, first['import_id'], *self.text_file('[2] Lặp lại.\n', 'part-001 (1).md'))
        checked = imports.check(d.name, first['import_id'], [1, 2])
        self.assertEqual((checked['report']['parts'][1]['repeats'], checked['report']['parts'][1]['repeats_of']), ([2], ['part-001.md']))
        imports.add_part(d.name, first['import_id'], *self.text_file('Không có mã.\n', 'c.txt'))
        checked = imports.check(d.name, first['import_id'], [1, 3])
        self.assertIn('Some files have no [n] numbers', checked['report']['blocked'])
        self.assertFalse(checked['ready'])
        for order in ([], [1, 1], [9], ['1']):
            with self.assertRaisesRegex(ValueError, 'Invalid file order'): imports.check(d.name, first['import_id'], order)
        imports.add_part(d.name, first['import_id'], *self.text_file('{"start_ms": 0, "end_ms": 1, "text_vi": "x"}\n', 'd.jsonl'))
        self.assertIn('Do not mix JSONL with text files', imports.check(d.name, first['import_id'], [1, 4])['report']['blocked'])

    def test_only_the_text_stages_take_several_files(self):
        d = self.workflow(); self.transcribed(d); update_job(d, status='PAUSED')
        prepared = self.load(d, 'TRANSLATION', '你好。\n', 'zh.txt')
        with self.assertRaisesRegex(ValueError, 'takes one file'): imports.add_part(d.name, prepared['import_id'], *self.text_file('再见。\n', 'zh2.txt'))

    def test_a_manual_workflow_cuts_its_text_with_tool_7s_last_settings(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        manage.create(tool='split', source_job=d.name, split={'max_chars': 700, 'prompt': False, 'prompt_text': ''})
        self.assertEqual(mt.saved_split()['max_chars'], 700)
        other = self.workflow(manual=True)
        self.assertEqual((read_json(other / 'job.json')['split']['max_chars'], read_json(other / 'job.json')['split']['prompt']), (700, False))
        self.assertEqual(read_json(self.workflow() / 'job.json').get('split'), None)        # a machine-translated workflow does not cut

    def test_a_loaded_file_belongs_to_one_run_and_one_stage_and_is_used_once(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        other = self.workflow(manual=True); self.transcribed(other)
        prepared = self.load(d, 'MODERATION', '[1] A.\n[2] B.\n')
        with self.assertRaisesRegex(ValueError, 'another stage'): manage.reprocess(d.name, 'TTS', import_id=prepared['import_id'])
        with self.assertRaisesRegex(ValueError, 'another stage'): manage.reprocess(other.name, 'MODERATION', import_id=prepared['import_id'])
        with self.assertRaisesRegex(ValueError, 'no longer available'): manage.reprocess(d.name, 'MODERATION', import_id='f' * 32)
        manage.reprocess(d.name, 'MODERATION', import_id=prepared['import_id'])
        with self.assertRaisesRegex(ValueError, 'no longer available'): manage.reprocess(d.name, 'MODERATION', import_id=prepared['import_id'])

    def test_the_run_must_be_stopped_before_a_file_is_loaded(self):
        d = self.workflow(manual=True); self.transcribed(d)
        prepared = self.load(d, 'MODERATION', '[1] A.\n[2] B.\n')
        with self.assertRaisesRegex(ValueError, 'Pause or finish'): manage.reprocess(d.name, 'MODERATION', import_id=prepared['import_id'])

    def test_a_file_can_start_the_run_at_voice_generation(self):
        d = self.workflow(); self.transcribed(d)
        update_job(d, status='PAUSED')
        prepared = self.load(d, 'TTS', 'Xin chào.\n\nĐoạn mới.\n')
        manage.reprocess(d.name, 'TTS', import_id=prepared['import_id'])
        steps = read_json(d / 'job.json')['steps']
        self.assertEqual((steps['TRANSLATION']['origin'], steps['MODERATION']['origin']), ('skipped', 'import'))
        code, seen = self.go(d)
        self.assertEqual((code, seen), (0, ['tts', 'subtitle']))
        files = self.published(d)
        self.assertEqual((files['MODERATED_JSONL']['origin'], files['MODERATION_RESULT']['status']), ('import', 'AVAILABLE'))
        self.assertNotIn('VI_JSONL', files)          # the skipped Translation has nothing of its own to publish

    def test_a_chinese_text_can_start_the_run_at_translation(self):
        d = self.workflow(); self.transcribed(d); update_job(d, status='FAILED')
        prepared = self.load(d, 'TRANSLATION', '你好世界。\n再见。\n', 'zh.txt')
        self.assertEqual(prepared['report']['mode'], 'zh')
        manage.reprocess(d.name, 'TRANSLATION', import_id=prepared['import_id'])
        code, seen = self.go(d)
        self.assertEqual((code, seen), (0, ['translation', 'moderation', 'tts', 'subtitle']))
        self.assertIn('你好世界。', (d / 'transcript.zh.md').read_text(encoding='utf-8'))
        self.assertEqual(self.published(d)['ZH_MD']['origin'], 'import')

    def test_an_audio_file_can_start_the_run_at_transcription(self):
        d = self.workflow(); update_job(d, status='FAILED')
        path = self.data / 'uploads' / f'{uuid.uuid4()}.upload'; path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), np.zeros(16000, dtype=np.int16), 16000, format='WAV', subtype='PCM_16')
        prepared = imports.prepare(d.name, 'TRANSCRIPTION', str(path), 'speech.wav', 'audio/wav')
        self.assertEqual(prepared['report']['mode'], 'audio')
        manage.reprocess(d.name, 'TRANSCRIPTION', import_id=prepared['import_id'])
        saved = read_json(d / 'job.json')
        self.assertTrue((d / 'source' / 'audio.wav').is_file())
        self.assertEqual((saved['steps']['DOWNLOAD']['origin'], saved['source_ext'], saved['source_upload'], saved['steps']['TRANSCRIPTION']['state']), ('import', '.wav', True, 'PENDING'))
        self.assertAlmostEqual(saved['duration_ms'], 1000, delta=50)

    def test_a_tool_takes_no_loaded_file(self):
        upload, name = self.text_file('你好\n', 'zh.txt')
        tool = manage.create(tool='translation', upload=upload, input_name=name, mime='text/plain')
        with self.assertRaisesRegex(ValueError, 'workflows only'): imports.prepare(tool['id'], 'MODERATION', *self.text_file('[1] A\n'), 'text/plain')

    def test_translating_again_without_a_file_gives_the_job_back_to_the_machine(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        manage.reprocess(d.name, 'TRANSLATION')
        self.assertNotIn('manual_translation', read_json(d / 'job.json'))
        code, seen = self.go(d)
        self.assertEqual((code, seen[0]), (0, 'translation'))

    def test_the_awaiting_run_can_be_deleted_like_a_stopped_one(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        manage.hard_delete(d.name, 1)
        self.assertFalse(d.exists())

    # --- tool 7 -----------------------------------------------------------------------------------------------------------
    def test_tool_7_cuts_the_chinese_text_of_a_finished_run_into_numbered_parts(self):
        d = self.workflow(manual=True); self.transcribed(d); self.go(d)
        tool = manage.create(tool='split', source_job=d.name, split={'max_chars': 500, 'prompt': True, 'prompt_text': 'Dịch nhé'})
        t = results.workspace(tool['id'])
        self.assertEqual(read_json(t / 'job.json')['tool_steps'], ['SPLIT'])
        with patch('audio_translate.workflow.orchestrator.subprocess.run', side_effect=lambda command, **kw: (mt.run_split(t), Mock(returncode=0))[1]):
            self.assertEqual(run(t), 0)
        saved = read_json(t / 'job.json')
        self.assertEqual((saved['status'], saved['split']['parts'], saved['split']['paragraphs']), ('COMPLETED', 1, 2))
        out = results.destination(t.name)
        entries = {f['type']: f for f in read_json(out / 'outputs.json')['files']}
        self.assertEqual({k for k in entries if k.startswith('SPLIT')}, {'SPLIT_ZIP', 'SPLIT_001'})
        part = (out / entries['SPLIT_001']['path']).read_text(encoding='utf-8')
        self.assertTrue(part.startswith('Dịch nhé') and '[1] 你好。再见。' in part and '[2] 新的一段。结束。' in part)
        import zipfile
        with zipfile.ZipFile(out / entries['SPLIT_ZIP']['path']) as bundle: self.assertEqual(bundle.namelist(), ['part-001.md'])

    def test_tool_7_takes_a_text_file_too_and_needs_exactly_one_source(self):
        upload, name = self.text_file('第一段\n第二段\n', 'zh.txt')
        tool = manage.create(tool='split', upload=upload, input_name=name, mime='text/plain', split={'max_chars': 500})
        self.assertEqual(read_json(results.workspace(tool['id']) / 'job.json')['split']['max_chars'], 500)
        with self.assertRaisesRegex(ValueError, 'Choose a run'): manage.create(tool='split')
        with self.assertRaisesRegex(ValueError, 'Invalid part size'): manage.create(tool='split', source_job='x', split={'max_chars': 10})
        with self.assertRaisesRegex(ValueError, 'Unsupported tool'): manage.create(tool='translation', split={'max_chars': 600})

    def test_a_run_without_chinese_text_cannot_be_split(self):
        d = self.workflow()
        with self.assertRaisesRegex(ValueError, 'no Chinese text'): manage.create(tool='split', source_job=d.name)


if __name__ == '__main__':
    unittest.main()
