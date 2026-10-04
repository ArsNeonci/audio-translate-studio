import unittest

from audio_translate.translation.hymt_translation import TranslationAdapter, default_settings
from audio_translate.translation.names import detect, reading


class NameTests(unittest.TestCase):
    def test_readings_use_han_viet_and_skip_uncertain_characters(self):
        self.assertEqual(reading('张倩倩'), 'Trương Thiến Thiến')
        self.assertEqual(reading('李强'), 'Lý Cường')
        self.assertEqual(reading('宋轩'), 'Tống Hiên')
        self.assertEqual(reading('欧阳婉'), 'Âu Dương Uyển')
        self.assertIsNone(reading('张嘛'))   # unknown given-name character: never guessed
        self.assertIsNone(reading('他们'))   # not a surname

    def test_detection_keeps_frequent_names_and_drops_words(self):
        rows = ['张倩倩说李强好。', '李强家很穷，', '张倩倩不信。', '李强来了，', '张倩倩哭了。',
                '倩倩别哭，', '倩倩你听我说。', '李强家里没钱。', '那天我们很高兴。', '那天很冷，', '那天下雨。']
        names = {item['source']: item['target'] for item in detect(rows)}
        self.assertEqual(names['张倩倩'], 'Trương Thiến Thiến')
        self.assertEqual(names['李强'], 'Lý Cường')
        self.assertEqual(names['倩倩'], 'Thiến Thiến')   # alias also used without the surname
        self.assertNotIn('李强家', names)                # name + ordinary word
        self.assertNotIn('那天', names)                  # ambiguous surname needs a name tag

    def test_group_split_validates_markers_and_rows(self):
        texts = ['看着那条手链，', '宋轩冷笑一声，', '真是晦气。']
        ok, problem = TranslationAdapter.split_group(
            '<target><s1>Nhìn chiếc vòng tay đó,</s1><s2>Tống Hiên cười lạnh,</s2><s3>thật xui xẻo.</s3></target>', texts)
        self.assertEqual((ok, problem), (['Nhìn chiếc vòng tay đó,', 'Tống Hiên cười lạnh,', 'thật xui xẻo.'], None))
        for bad in ('<s1>a</s1><s2>b</s2>', '<s1>a</s1><s2>b</s2><s3>c</s3><s4>d</s4>',
                    '<s1>a</s1><s2>宋轩</s2><s3>c</s3>', 'Ghi chú <s1>a</s1><s2>b</s2><s3>c</s3>'):
            self.assertIsNone(TranslationAdapter.split_group(bad, texts)[0], bad)

    def test_terms_prefer_configured_glossary_and_drop_redundant_aliases(self):
        settings = default_settings()
        settings['glossary'] = [{'source': '张倩倩', 'target': 'Thiến Thiến'}]
        adapter = TranslationAdapter(settings)
        adapter.names = [{'source': '张倩倩', 'target': 'Trương Thiến Thiến'}, {'source': '倩倩', 'target': 'Thiến Thiến'}]
        self.assertEqual(adapter.terms('张倩倩来了'), [('张倩倩', 'Thiến Thiến')])
        self.assertEqual(adapter.terms('张倩倩和倩倩'), [('张倩倩', 'Thiến Thiến'), ('倩倩', 'Thiến Thiến')])


if __name__ == '__main__':
    unittest.main()
