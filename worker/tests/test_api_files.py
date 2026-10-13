"""The local API's saved-file answers (audio_translate/api/files.py): paging a text preview without cutting a character,
ranges, and JavaScript's Number() for query values. Ported from lib/server/file-response.ts; the expected values follow it."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_translate.api import files


class FakeRequest:
    def __init__(self, query=None, headers=None):
        self.query_params, self.headers = query or {}, {k.lower(): v for k, v in (headers or {}).items()}


def body(response):
    if hasattr(response, 'body_iterator'):
        import asyncio
        async def collect(): return b''.join([piece async for piece in response.body_iterator])
        return asyncio.run(collect())
    return response.body


class FilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, data):
        path = self.root / name; path.write_bytes(data); return str(path)

    def page(self, file, offset=0):
        response = files.saved_file_response(FakeRequest({'preview': '1', 'offset': str(offset)}), file, True)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.body)

    def test_preview_pages_end_on_a_line_and_join_back_to_the_file(self):
        text = ''.join(f'dòng {i} 你好\n' for i in range(9000)).encode()
        file = self.write('a.md', text)
        offset, parts = 0, []
        while offset is not None:
            value = self.page(file, offset)
            self.assertLessEqual(len(value['content'].encode()), 65536)
            if value['next_offset'] is not None: self.assertTrue(value['content'].endswith('\n'))
            parts.append(value['content']); offset = value['next_offset']
        self.assertEqual(''.join(parts).encode(), text)
        self.assertGreater(len(parts), 2)

    def test_a_page_without_a_newline_stops_before_a_split_character(self):
        text = ('王' * 30000).encode()            # 3 bytes each, no newline: 65536 is not a multiple of 3
        file = self.write('b.txt', text)
        first = self.page(file)
        self.assertEqual(first['next_offset'], 65535)  # the last whole character ends at 65535
        self.assertEqual(first['content'], '王' * 21845)
        self.assertEqual(self.page(file, 65535)['content'], '王' * (30000 - 21845))

    def test_a_whole_json_file_is_pretty_printed(self):
        file = self.write('c.json', json.dumps({'a': [1, 2], 'b': 'Việt'}).encode())
        self.assertEqual(self.page(file)['content'], '{\n  "a": [\n    1,\n    2\n  ],\n  "b": "Việt"\n}')

    def test_bad_preview_offsets(self):
        file = self.write('d.md', b'abc')
        for bad in ('-1', '4', '1.5', 'x', 'Infinity'):
            response = files.saved_file_response(FakeRequest({'preview': '1', 'offset': bad}), file, True)
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(self.page(file, 3), {'content': '', 'offset': 3, 'next_offset': None, 'size': 3})
        self.assertEqual(self.page(file, '')['content'], 'abc')   # an empty offset is 0, as Number('') is

    def test_ranges(self):
        data = bytes(range(100))
        file = self.write('e.wav', data)
        def get(asked):
            response = files.saved_file_response(FakeRequest(headers={'Range': asked} if asked else None), file, True)
            return response.status_code, response.headers.get('content-range'), body(response)
        self.assertEqual(get(None), (200, None, data))
        self.assertEqual(get('bytes=10-19'), (206, 'bytes 10-19/100', data[10:20]))
        self.assertEqual(get('bytes=90-'), (206, 'bytes 90-99/100', data[90:]))
        self.assertEqual(get('bytes=-5'), (206, 'bytes 95-99/100', data[95:]))
        self.assertEqual(get('bytes=95-500'), (206, 'bytes 95-99/100', data[95:]))
        for bad in ('bytes=100-', 'bytes=50-10', 'bytes=-', 'items=0-5', 'bytes=0-1,5-6'):
            self.assertEqual(get(bad)[:2], (416, 'bytes */100'), bad)

    def test_headers_and_the_licence_for_inline_reads(self):
        file = self.write('f.md', b'# hi')
        response = files.saved_file_response(FakeRequest(), file, True)
        self.assertEqual((response.media_type, response.headers['content-disposition'], response.headers['cache-control'], response.headers['accept-ranges']),
                         ('text/markdown; charset=utf-8', 'attachment; filename="f.md"', 'no-store', 'bytes'))
        with patch.object(files, 'license_denial', return_value='DENIED') as denial:
            self.assertEqual(files.saved_file_response(FakeRequest(), file, False), 'DENIED')
            denial.assert_called_once_with(False)   # viewing never refreshes the lease
        empty = self.write('g.txt', b'')
        response = files.saved_file_response(FakeRequest(), empty, True)
        self.assertEqual((response.status_code, response.headers['content-length'], response.body), (200, '0', b''))

    def test_js_number(self):
        for text, value in (('', 0), (' 3 ', 3), ('1e2', 100), ('0x10', 16), ('2.5', 2.5)): self.assertEqual(files.js_number(text), value, text)
        for text in ('x', '1_000', 'nan', 'inf'): self.assertNotEqual(files.js_number(text), files.js_number(text), text)   # NaN


if __name__ == '__main__':
    unittest.main()
