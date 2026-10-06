import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_translate.core.storage import atomic_json, read_json
from audio_translate.moderation import address
from audio_translate.moderation.rules import ReplacementRules
from audio_translate.workflow.postprocess import moderate


def row(zh, vi):
    return {"start_ms": 0, "end_ms": 0, "text_zh": zh, "text_vi": vi}


def person(source, gender, role="other", rank="peer", auto=False, aliases=None, third="", you=""):
    return {"id": source, "source": source, "aliases": aliases or [source], "target": source, "gender": gender,
            "role": role, "rank": rank, "third": third, "you": you, "auto": auto}


def sheet(*people):
    return address.validate_sheet({"version": 1, "characters": list(people)})


def run(resolver, rows):
    return [resolver.apply(r) for r in rows]


class AddressTests(unittest.TestCase):
    def test_mother_fixes_wrong_gender_from_asr(self):
        mother = person("我妈", "female", "family", "elder", auto=True, aliases=["我妈", "妈妈"], third="mẹ", you="mẹ")
        r = address.Resolver(sheet(mother), "drama")
        out = run(r, [row("我妈笑了笑，", "Mẹ tôi cười,"), row("说，", "nói,"), row("可这次是他的儿子，", "Nhưng lần này là con trai của anh ấy,")])
        self.assertEqual(out[-1], ("Nhưng lần này là con trai của mẹ,", 1))

    def test_antagonist_register_follows_profile(self):
        sil = person("嫂子", "female", "antagonist", "senior")
        rows = [row("嫂子没有工作，", "Chị dâu không có việc làm,"), row("她又找了老公。", "Cô ấy lại tìm chồng.")]
        self.assertEqual(run(address.Resolver(sheet(sil), "drama"), rows)[-1][0], "Chị ta lại tìm chồng.")
        survival = person("李四", "male", "antagonist", "peer")
        rows = [row("李四来了，", "Lý Tứ đến,"), row("他笑了。", "Anh ấy cười.")]
        self.assertEqual(run(address.Resolver(sheet(survival), "survival"), rows)[-1][0], "Hắn cười.")

    def test_two_people_in_scope_never_flip_gender(self):
        a, b = person("张三", "male", "antagonist"), person("王丽", "female", "antagonist")
        rows = [row("张三和王丽吵架，", "Trương Tam và Vương Lệ cãi nhau,"), row("她哭了。", "Anh ấy khóc.")]
        self.assertEqual(run(address.Resolver(sheet(a, b), "drama"), rows)[-1], ("Anh ấy khóc.", 0))

    def test_unconfirmed_gender_only_changes_register(self):
        guess = person("王丽", "female", "antagonist", auto=True)
        rows = [row("王丽来了，", "Vương Lệ đến,"), row("他坐下。", "Anh ấy ngồi xuống.")]
        self.assertEqual(run(address.Resolver(sheet(guess), "drama"), rows)[-1], ("Anh ấy ngồi xuống.", 0))
        rows = [row("王丽来了，", "Vương Lệ đến,"), row("她坐下。", "Cô ấy ngồi xuống.")]
        self.assertEqual(run(address.Resolver(sheet(guess), "drama"), rows)[-1][0], "Cô ta ngồi xuống.")

    def test_mixed_gender_rows_are_skipped(self):
        a = person("张三", "male", "antagonist")
        rows = [row("张三说，", "Trương Tam nói,"), row("他送她礼物。", "Anh ấy tặng cô ấy quà.")]
        self.assertEqual(run(address.Resolver(sheet(a), "drama"), rows)[-1], ("Anh ấy tặng cô ấy quà.", 0))

    def test_vocative_needs_a_bare_alias(self):
        mother = person("我妈", "female", "family", "elder", aliases=["我妈", "妈妈", "妈"], you="mẹ")
        friend = person("倩倩", "female", "antagonist")
        r = address.Resolver(sheet(mother, friend), "drama")
        self.assertEqual(r.apply(row("倩倩，你怎么了？", "Thiến Thiến, bạn sao vậy?"))[0], "Thiến Thiến, cô sao vậy?")
        self.assertEqual(r.apply(row("你死了是妈，", "Bạn chết là do mẹ,"))[0], "Bạn chết là do mẹ,")
        self.assertEqual(r.apply(row("妈，", "Mẹ,"))[0], "Mẹ,")
        self.assertEqual(r.apply(row("你和你的朋友呢？", "Bạn và bạn bè của bạn thì sao?"))[0], "Mẹ và bạn bè của mẹ thì sao?")

    def test_neutral_profile_ignores_drafts_but_keeps_manual_forms(self):
        drafted = person("我妈", "female", "family", "elder", auto=True, third="mẹ")
        self.assertEqual(run(address.Resolver(sheet(drafted), "neutral"), [row("我妈说，", "Mẹ nói,"), row("她笑。", "Bà ấy cười.")])[-1][1], 0)
        manual = person("我妈", "female", "family", "elder", third="mẹ")
        self.assertEqual(run(address.Resolver(sheet(manual), "neutral"), [row("我妈说，", "Mẹ nói,"), row("她笑。", "Bà ấy cười.")])[-1][0], "Mẹ cười.")

    def test_sheet_validation(self):
        with self.assertRaises(ValueError): sheet(person("张三", "robot"))
        with self.assertRaises(ValueError): sheet(person("张三", "male", role="boss"))
        with self.assertRaises(ValueError): sheet(person("张三", "male", third="<script>"))
        with self.assertRaises(ValueError): address.validate_profile("horror")

    def test_draft_uses_glossary_aliases_name_chars_and_kinship(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "working").mkdir()
            atomic_json(Path(temp) / "working" / "name-glossary.json", {"version": 1, "names": [
                {"source": "张倩倩", "target": "Trương Thiến Thiến", "count": 9, "auto": True},
                {"source": "倩倩", "target": "Thiến Thiến", "count": 3, "auto": True},
                {"source": "李强", "target": "Lý Cường", "count": 9, "auto": True}]})
            rows = [row("我妈来了。", "Mẹ đến."), row("我妈走了。", "Mẹ đi."), row("我妈哭了。", "Mẹ khóc."), row("张倩倩和李强。", "x")]
            draft = {c["source"]: c for c in address.draft(temp, rows)["characters"]}
        self.assertEqual(draft["张倩倩"]["aliases"], ["张倩倩", "倩倩"])
        self.assertEqual((draft["张倩倩"]["gender"], draft["李强"]["gender"]), ("female", "male"))
        self.assertEqual((draft["我妈"]["role"], draft["我妈"]["you"]), ("family", "mẹ"))


class AddressModerationTests(unittest.TestCase):
    def setUp(self):
        license_patch = patch("audio_translate.core.license_gate.assert_allowed", return_value=True)
        license_patch.start(); self.addCleanup(license_patch.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.job = self.root / "jobs" / "test"
        (self.job / "working").mkdir(parents=True)
        rows = [row("嫂子没有工作，", "Chị dâu không có việc làm,"), row("她又找了老公。", "Cô ấy lại tìm chồng.")]
        (self.job / "transcript.vi.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        atomic_json(address.characters_path(self.job), {"version": 1, "characters": [person("嫂子", "female", "antagonist", "senior")]})
        self.rules = ReplacementRules(self.root / "config")

    def run_profile(self, profile):
        atomic_json(self.job / "job.json", {"status": "TRANSLATION_COMPLETED", "workflow_version": 2, "selected_address_profile": profile})
        for name in ("moderation.done.json",): (self.job / "working" / name).unlink(missing_ok=True)
        moderate(self.job, self.rules)
        moderated = [json.loads(l) for l in (self.job / "transcript.vi.moderated.jsonl").read_text(encoding="utf-8").splitlines()]
        return moderated, read_json(self.job / "moderation-result.json")

    def test_profile_changes_moderated_text_and_reports_stats(self):
        moderated, stats = self.run_profile("drama")
        self.assertEqual(moderated[1]["text_vi_moderated"], "Chị ta lại tìm chồng.")
        self.assertEqual(moderated[1]["text_vi"], "Cô ấy lại tìm chồng.")
        self.assertEqual((stats["address_profile"], stats["address_replacements"]), ("drama", 1))

    def test_neutral_keeps_legacy_output(self):
        moderated, stats = self.run_profile("neutral")
        self.assertEqual(moderated[1]["text_vi_moderated"], "Cô ấy lại tìm chồng.")
        self.assertNotIn("address_profile", stats)
        self.assertNotIn("address_changes", moderated[1])


if __name__ == "__main__":
    unittest.main()
