"""The community moderation list the app starts with: put in once, then the person's own (edit, delete), never put back."""
import json
from pathlib import Path
import tempfile
import unittest

from audio_translate.moderation import rules as rules_module
from audio_translate.moderation.rules import ReplaceEngine, ReplacementRules

SHIPPED = [{'source': 'Giết', 'replacement': 'Hạ gục'}, {'source': 'Thi thể', 'replacement': 'Đăng xuất'}, {'source': 'Lồn', 'replacement': '[Bíp]'}]


class CommunityRulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / 'config'

    def service(self, loader=lambda: SHIPPED):
        return ReplacementRules(self.dir, seed=loader)

    def test_the_first_read_puts_the_list_in_and_every_rule_is_an_ordinary_one(self):
        service = self.service()
        listed = service.list()
        self.assertEqual([(r['source'], r['replacement']) for r in listed['rules']], [(r['source'], r['replacement']) for r in SHIPPED])
        self.assertEqual(len({r['id'] for r in listed['rules']}), 3)
        first = listed['rules'][0]
        service.mutate('edit', {'id': first['id'], 'source': 'Giết', 'replacement': 'Hạ'})
        service.mutate('delete', {'id': listed['rules'][1]['id']})
        service.mutate('add', {'source': 'Chém', 'replacement': 'Tác động'})
        after = service.list()['rules']
        self.assertEqual([(r['source'], r['replacement']) for r in after], [('Giết', 'Hạ'), ('Lồn', '[Bíp]'), ('Chém', 'Tác động')])

    def test_what_the_person_deleted_is_not_put_back_and_all_rules_can_be_removed(self):
        service = self.service()
        for rule in service.list()['rules']: service.mutate('delete', {'id': rule['id']})
        self.assertEqual(self.service().list()['rules'], [])                       # a new service, the same folder: still empty
        self.assertEqual(self.service(lambda: SHIPPED + [{'source': 'Bắn', 'replacement': 'Hạ gục'}]).list()['rules'], [])

    def test_rules_the_person_already_has_are_kept_and_only_missing_words_are_added(self):
        self.dir.mkdir(parents=True)
        (self.dir / 'replacement-rules.json').write_text(json.dumps([{'id': 'mine', 'source': 'Giết', 'replacement': 'Kết thúc'}, {'id': 'x', 'source': 'thế giới', 'replacement': 'các bạn'}]), encoding='utf-8')
        rules = self.service().list()['rules']
        self.assertEqual(rules[0], {'id': 'mine', 'source': 'Giết', 'replacement': 'Kết thúc'})   # their wording wins
        self.assertEqual([r['source'] for r in rules], ['Giết', 'thế giới', 'Thi thể', 'Lồn'])

    def test_a_list_that_cannot_be_read_yet_is_tried_again_and_nothing_is_marked_done(self):
        def broken(): raise RuntimeError('not authorised yet')
        service = self.service(broken)
        self.assertEqual(service.list()['rules'], [])
        self.assertFalse((self.dir / 'replacement-rules.seeded.json').exists())
        self.assertEqual(len(self.service().list()['rules']), 3)                   # later, when it can be read

    def test_the_shipped_list_is_valid_for_the_engine_and_replaces_whole_words_it_names(self):
        shipped = json.loads((rules_module.ROOT / 'worker' / 'config' / 'community-rules.json').read_text(encoding='utf-8'))
        self.assertGreater(len(shipped), 500)
        engine = ReplaceEngine([{'id': str(i), **item} for i, item in enumerate(shipped)])     # no empty or duplicate source
        text, counts = engine.apply('Giết rồi Thi thể ở đó.')
        self.assertEqual(text, 'Hạ gục rồi Đăng xuất ở đó.')
        self.assertEqual(sum(counts.values()), 2)


if __name__ == '__main__':
    unittest.main()
