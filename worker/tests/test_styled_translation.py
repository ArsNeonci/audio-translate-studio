import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from audio_translate.core.storage import atomic_json, read_json
from audio_translate.moderation import address
from audio_translate.moderation.flow import Flow
from audio_translate.translation import lexicon
from audio_translate.translation.hymt_translation import TranslationAdapter, default_settings, gender_problem, harmonize_gender
from audio_translate.workflow.postprocess import _translate, export_translation_partial, moderate
from audio_translate.moderation.rules import ReplacementRules


def person(source, gender, role="other", rank="peer", auto=False, sure=False, aliases=None):
    return {"id": source, "source": source, "aliases": aliases or [source], "target": source, "gender": gender,
            "role": role, "rank": rank, "third": "", "you": "", "auto": auto, "sure": sure}


def sheet(*people):
    return address.validate_sheet({"version": 1, "characters": list(people)})


def zh(text):
    return {"text_zh": text}


class RepairTests(unittest.TestCase):
    def repair(self, rows, *people):
        resolver = address.Resolver(sheet(*people), "neutral")
        return [resolver.repair(r) for r in rows]

    def test_pronoun_gender_follows_the_confirmed_character(self):
        out = self.repair(["张倩倩来了，", "但他不领情。"], person("张倩倩", "female"))
        self.assertEqual(out[-1], "但她不领情。")

    def test_plural_dangling_and_double_pronouns_are_left_alone(self):
        woman = person("张倩倩", "female")
        for text in ("他们不领情。", "我知道他们家他家很贵，", "表弟说他，", "他看见他了。"):
            self.assertEqual(self.repair(["张倩倩来了，", text], woman)[-1], text, text)

    def test_unconfirmed_gender_never_flips(self):
        guess = person("张倩倩", "female", auto=True, sure=False)
        self.assertEqual(self.repair(["张倩倩来了，", "他笑了。"], guess)[-1], "他笑了。")
        sure = person("张倩倩", "female", auto=True, sure=True)
        self.assertEqual(self.repair(["张倩倩来了，", "他笑了。"], sure)[-1], "她笑了。")

    def test_nearby_opposite_pronoun_or_noun_blocks_the_flip(self):
        woman = person("顾念念", "female", auto=True, sure=True)
        rows = ["他从兜里掏出一张纸，", "上面是顾念念的字迹。", "我找出毕业照，", "他指了指合照，"]
        self.assertEqual(self.repair(rows, woman)[-1], "他指了指合照，")
        rows = ["顾念念来了，", "我低估了我妈对哥的爱，", "他来闹只是前招。"]
        self.assertEqual(self.repair(rows, woman)[-1], "他来闹只是前招。")
        rows = ["我是被顾念念吵醒的，", "学校里的男生很多，", "他举着手机。"]
        self.assertEqual(self.repair(rows, woman)[-1], "他举着手机。")
        rows = ["我是被顾念念吵醒的，", "男生宿舍丢了东西，", "他举着手机。"]  # a dorm is not a person
        self.assertEqual(self.repair(rows, woman)[-1], "她举着手机。")

    def test_two_people_in_scope_never_flip(self):
        a, b = person("张倩倩", "female"), person("李强", "male")
        self.assertEqual(self.repair(["张倩倩和李强来了，", "他笑了。"], a, b)[-1], "他笑了。")

    def test_draft_marks_sure_only_from_the_name_itself(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "working").mkdir()
            atomic_json(Path(temp) / "working" / "name-glossary.json", {"version": 1, "names": [
                {"source": "张倩倩", "target": "Trương Thiến Thiến", "count": 9, "auto": True},
                {"source": "宋轩", "target": "Tống Hiên", "count": 9, "auto": True},
                {"source": "穆淑泽", "target": "Mục Thục Trạch", "count": 9, "auto": True}]})
            # ASR writes 她 around the male name; that must not make 宋轩 "sure".
            rows = [zh("宋轩推门而入，"), zh("她长相帅气，"), zh("宋轩看了她一眼，"), zh("张倩倩笑了。"), zh("表弟穆淑泽来了。")]
            draft = {c["source"]: c for c in address.draft(temp, rows)["characters"]}
        self.assertTrue(draft["张倩倩"]["sure"])
        self.assertFalse(draft["宋轩"]["sure"])
        self.assertFalse(draft["穆淑泽"]["sure"])  # one 淑 is not enough: he is the male cousin


class GenderCheckTests(unittest.TestCase):
    def test_mixed_genders_for_a_single_pronoun_are_flagged(self):
        self.assertEqual(gender_problem("可能是和她男朋友在一起吧。", "Có lẽ anh ấy đang ở với bạn trai của cô ấy."), "pronoun genders disagree")
        self.assertIsNone(gender_problem("可能是和她男朋友在一起吧。", "Có lẽ cô ấy đang ở cùng bạn trai của mình."))
        self.assertIsNone(gender_problem("他送她礼物。", "Anh ấy tặng cô ấy quà."))  # two pronouns: mixed is legitimate
        self.assertIsNone(gender_problem("张倩倩给她打电话，", "Trương Thiến Thiến gọi cô ấy, anh ta", names=["张倩倩"]))

    def adapter(self, outputs):
        adapter = TranslationAdapter(default_settings())
        adapter.model = SimpleNamespace(tokenize=lambda *a, **k: [0] * 10)
        adapter.gender_check = True
        calls = []

        def complete(prompt, slot, budget, seed, temperature):
            calls.append(temperature)
            return outputs[min(len(calls), len(outputs)) - 1], True
        adapter.complete = complete
        adapter.calls = calls
        return adapter

    def test_inconsistent_group_is_retried_and_the_consistent_one_wins(self):
        bad = "<target><s1>Có lẽ anh ấy đang ở với bạn trai của cô ấy.</s1></target>"
        good = "<target><s1>Có lẽ cô ấy đang ở cùng bạn trai.</s1></target>"
        adapter = self.adapter([bad, good])
        self.assertEqual(adapter.infer_group(["可能是和她男朋友在一起吧。"]), ["Có lẽ cô ấy đang ở cùng bạn trai."])
        self.assertEqual(len(adapter.calls), 2)

    def test_persistent_inconsistency_falls_back_to_row_translation(self):
        from audio_translate.translation.hymt_translation import GroupFailure
        bad = "<target><s1>Có lẽ anh ấy đang ở với bạn trai của cô ấy.</s1></target>"
        adapter = self.adapter([bad, bad])
        with self.assertRaises(GroupFailure):
            adapter.infer_group(["可能是和她男朋友在一起吧。"])

    def test_harmonize_follows_the_chinese_pronoun(self):
        self.assertEqual(harmonize_gender("可能是和她男朋友在一起吧。", "Có lẽ anh ấy đang ở với bạn trai của cô ấy."), "Có lẽ cô ấy đang ở với bạn trai của cô ấy.")
        self.assertEqual(harmonize_gender("他是她男朋友。", "Anh ấy là bạn trai của cô ấy."), "Anh ấy là bạn trai của cô ấy.")  # two pronouns: untouched
        self.assertEqual(harmonize_gender("可能是和他女朋友在一起吧。", "Có lẽ anh ấy ở với bạn gái của cô ta."), "Có lẽ anh ấy ở với bạn gái của anh ta.")
        self.assertEqual(harmonize_gender("她来了。", "Anh ta tới, Cô ấy cười."), "Cô ta tới, Cô ấy cười.")

    def test_row_translation_keeps_its_draft_when_every_attempt_disagrees(self):
        bad = "Có lẽ anh ấy đang ở với bạn trai của cô ấy."
        adapter = self.adapter([bad, bad, bad])
        adapter.prompt = lambda *a, **k: "p"
        adapter.runtime = object()  # skip the in-process resource checks
        with patch("audio_translate.translation.hymt_translation.check_cancel"), patch.dict("sys.modules", {"psutil": __import__("psutil"), "llama_cpp": SimpleNamespace(llama_set_n_threads=lambda *a: None)}):
            self.assertEqual(adapter.infer("可能是和她男朋友在一起吧。", ""), "Có lẽ cô ấy đang ở với bạn trai của cô ấy.")
        self.assertEqual(len(adapter.calls), 3)

    def test_check_is_off_for_legacy_jobs(self):
        bad = "<target><s1>Có lẽ anh ấy đang ở với bạn trai của cô ấy.</s1></target>"
        adapter = self.adapter([bad])
        adapter.gender_check = False
        adapter.infer_group(["可能是和她男朋友在一起吧。"])
        self.assertEqual(len(adapter.calls), 1)


class LexiconTests(unittest.TestCase):
    def test_entries_by_profile(self):
        self.assertIn("心虚", [e["source"] for e in lexicon.entries("neutral")])
        self.assertNotIn("重生", [e["source"] for e in lexicon.entries("neutral")])
        self.assertIn(("重生", "trọng sinh"), [(e["source"], e["target"]) for e in lexicon.entries("rebirth")])

    def test_terms_reach_the_prompt_only_when_the_phrase_occurs(self):
        adapter = TranslationAdapter(default_settings())
        adapter.lexicon = lexicon.entries("drama")
        block = adapter.glossary_block("李强虽然心虚，")
        self.assertIn("心虚 翻译成 chột dạ", block)
        self.assertEqual(adapter.glossary_block("他很大胆。"), "")  # 大胆 alone is deliberately not an entry
        adapter.lexicon = []
        self.assertEqual(adapter.glossary_block("李强虽然心虚，"), "")

    def test_invalid_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lex.json"
            path.write_text(json.dumps({"version": 1, "common": [{"source": "", "target": "x"}], "profiles": {}}), encoding="utf-8")
            with patch.dict("os.environ", {"GENRE_LEXICON_CONFIG": str(path)}):
                with self.assertRaises(ValueError): lexicon.entries("drama")


class FlowTests(unittest.TestCase):
    def test_lowercases_only_demonstrably_common_words_after_a_comma(self):
        texts = ["tôi chạy rồi cuối cùng ngã"] * 6 + ["Trương Thiến Thiến cười, Lý Cường đến, Rồi họ đi, Mumu về"]
        flow = Flow(texts, names=["Trương Thiến Thiến"])
        self.assertEqual(flow.apply("tôi bị đẩy xuống sông,", "Rồi tôi chết."), "rồi tôi chết.")
        self.assertEqual(flow.apply("tôi bị đẩy xuống sông,", "Lý Cường đến."), "Lý Cường đến.")        # capitalized pair
        self.assertEqual(flow.apply("tôi bị đẩy xuống sông,", "Trương Thiến Thiến đến."), "Trương Thiến Thiến đến.")
        self.assertEqual(flow.apply("tôi bị đẩy xuống sông,", "Mumu đến."), "Mumu đến.")              # rare word: kept
        self.assertEqual(flow.apply("tôi bị đẩy xuống sông.", "Rồi tôi chết."), "Rồi tôi chết.")      # sentence ended
        self.assertEqual(flow.apply("Tống Hiên nói lạnh lùng:", "Rồi tôi chết."), "Rồi tôi chết.")
        self.assertEqual(flow.apply("", "Rồi tôi chết."), "Rồi tôi chết.")


class StreamAdapter:
    """Records what the pipeline sends; returns a marker translation."""

    def __init__(self):
        self.sent, self.lexicon, self.gender_check, self.names = [], [], False, []

    def translate_stream(self, entries, lookup, save, save_row, fail_row):
        for owner, text, context, cached, recovery in entries:
            if cached is not None:
                save_row(owner, cached, cached=True); continue
            self.sent.append(text)
            if not text.strip():  # the real adapter yields no parts for an empty source
                save_row(owner, ""); continue
            vi = "VI " + hashlib.md5(text.encode()).hexdigest()[:6]  # no Chinese: it must pass output_problem
            if lookup(owner, 0, text) is None: save(owner, 0, text, vi)
            save_row(owner, vi)


class PipelineBase(unittest.TestCase):
    ROWS = ["张倩倩笑了，", "但他不领情。", "李强虽然心虚，"]

    def setUp(self):
        license_patch = patch("audio_translate.core.license_gate.assert_allowed", return_value=True)
        license_patch.start(); self.addCleanup(license_patch.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def job(self, name, **fields):
        job = self.root / name
        (job / "working").mkdir(parents=True)
        atomic_json(job / "job.json", {"status": "TRANSCRIPTION_COMPLETED", "workflow_version": 2, **fields})
        (job / "transcript.zh.jsonl").write_text("".join(json.dumps({"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": t}, ensure_ascii=False) + "\n"
                                                         for i, t in enumerate(self.ROWS)), encoding="utf-8")
        atomic_json(job / "working" / "name-glossary.json", {"version": 1, "names": []})
        atomic_json(address.characters_path(job), {"version": 1, "characters": [person("张倩倩", "female"), person("李强", "male")]})
        return job

    def run_job(self, job):
        adapter = StreamAdapter()
        _translate(job, adapter)
        return adapter, [json.loads(line) for line in (job / "transcript.vi.jsonl").read_text(encoding="utf-8").splitlines()]



class PipelineTests(PipelineBase):
    def test_styled_job_sends_repaired_chinese_but_stores_the_transcript(self):
        job = self.job("styled", selected_address_profile="drama")
        adapter, out = self.run_job(job)
        self.assertEqual(adapter.sent, ["张倩倩笑了，", "但她不领情。", "李强虽然心虚，"])
        self.assertEqual([r["text_zh"] for r in out], self.ROWS)
        self.assertTrue(adapter.gender_check)
        self.assertIn("心虚", [e["source"] for e in adapter.lexicon])
        self.assertEqual(json.loads((job / "working" / "gender-repair.json").read_text(encoding="utf-8"))["rows"], 1)

    def test_partial_export_matches_the_checkpoint_keys(self):
        job = self.job("export", selected_address_profile="drama")
        self.run_job(job)
        (job / "working" / "translation.done.json").unlink()
        result = export_translation_partial(job)
        self.assertEqual((result["rows"], result["complete"]), (3, True))

    def test_legacy_job_is_untouched(self):
        job = self.job("legacy")
        adapter, out = self.run_job(job)
        self.assertEqual(adapter.sent, self.ROWS)
        self.assertEqual((adapter.lexicon, adapter.gender_check), ([], False))
        self.assertFalse((job / "working" / "gender-repair.json").exists())

    def test_moderation_flow_applies_only_to_styled_jobs(self):
        def moderated(job):
            rows = [{"start_ms": 0, "end_ms": 1, "text_zh": "甲", "text_vi": "tôi chạy rồi cuối cùng ngã,"}] + \
                   [{"start_ms": i, "end_ms": i + 1, "text_zh": "乙", "text_vi": "tôi chạy rồi cuối cùng ngã."} for i in range(1, 6)] + \
                   [{"start_ms": 9, "end_ms": 10, "text_zh": "丙", "text_vi": "Rồi tôi chết."}]
            rows[5]["text_vi"] = "tôi bị đẩy xuống,"
            (job / "transcript.vi.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            moderate(job, ReplacementRules(self.root / "config"))
            return [json.loads(l)["text_vi_moderated"] for l in (job / "transcript.vi.moderated.jsonl").read_text(encoding="utf-8").splitlines()][-1]
        styled, legacy = self.job("m-styled", selected_address_profile="neutral"), self.job("m-legacy")
        self.assertEqual(moderated(styled), "rồi tôi chết.")
        self.assertEqual(moderated(legacy), "Rồi tôi chết.")



class CleanupTests(unittest.TestCase):
    def test_intro_split_across_rows_is_removed_and_story_text_kept(self):
        from audio_translate.translation.source_cleanup import clean
        rows = list(enumerate(["这一次我袖手旁观好看。", "小说千千万，", "悠悠，", "这里占一半，", "连好 wifi，", "备好瓜子饮料。",
                               "精彩故事现在开始，", "我才刚睁开眼睛，"], 1))
        out = clean(rows)
        self.assertEqual(out[1], "这一次我袖手旁观。")
        self.assertEqual([out[i] for i in range(2, 8)], [""] * 6)
        self.assertNotIn(8, out)
        rows = list(enumerate(["好看小，", "好看小说千千万，", "悠悠，", "这里占一半，", "连好 wifi，", "备好瓜子饮料。", "精彩故事，", "现在开始木木，"], 1))
        out = clean(rows)
        self.assertEqual(out[8], "木木，")
        self.assertEqual([out[i] for i in range(1, 8)], [""] * 7)

    def test_asr_corrections_and_untouched_rows(self):
        from audio_translate.translation.source_cleanup import clean
        out = clean([(1, "一定能把煤运都洗干净。"), (2, "医生苦苦婆心的叹了口气，"), (3, "小说很好看。")])
        self.assertEqual(out, {1: "一定能把霉运都洗干净。", 2: "医生苦口婆心的叹了口气，"})

    def test_intro_is_only_searched_near_the_start(self):
        from audio_translate.translation.source_cleanup import clean, config
        data = {**config(), "boilerplate_rows": 2}
        rows = list(enumerate(["一", "二", "小说千千万，悠悠，这里占一半，连好wifi，备好瓜子饮料。精彩故事现在开始，"], 1))
        self.assertEqual(clean(rows, data), {})


class DroppedRowPipelineTests(PipelineBase):
    ROWS = ["我死了。", "小说千千万，悠悠，这里占一半，连好wifi，备好瓜子饮料。", "精彩故事现在开始，", "我才睁开眼睛。"]

    def test_styled_job_drops_the_intro_but_keeps_rows_and_timestamps(self):
        job = self.job("styled", selected_address_profile="drama")
        adapter, out = self.run_job(job)
        self.assertEqual(len(out), 4)
        self.assertEqual([r["text_vi"] == "" for r in out], [False, True, True, False])
        self.assertEqual([r["text_zh"] for r in out], self.ROWS)
        self.assertEqual(read_json(job / "working" / "source-cleanup.json")["dropped_rows"], [2, 3])
        # Resume reuses the checkpoints, including the empty rows.
        (job / "working" / "translation.done.json").unlink()
        again, _ = self.run_job(job)
        self.assertEqual(again.sent, [])

    def test_legacy_job_still_translates_the_intro(self):
        adapter, out = self.run_job(self.job("legacy"))
        self.assertTrue(all(r["text_vi"] for r in out))


if __name__ == "__main__":
    unittest.main()
