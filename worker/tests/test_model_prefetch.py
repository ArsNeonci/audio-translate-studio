"""First-run download of the speech models: runs before the ASR workers, shows progress, resumes, retries, can be cancelled."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from audio_translate.core.control import Cancelled
from audio_translate.transcription import model_prefetch as prefetch


class ModelPrefetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / 'cache'
        self.job = Path(self.temp.name) / 'job'; (self.job / 'working').mkdir(parents=True)
        patcher = patch.dict(os.environ, {'MODELSCOPE_CACHE': str(self.cache)}); patcher.start(); self.addCleanup(patcher.stop)
        self.fetched = []
        # These tests are about the ModelScope path: no published bundle in this build.
        patcher = patch.object(prefetch, 'manifest_path', return_value=Path(self.temp.name) / 'no-bundle.json'); patcher.start(); self.addCleanup(patcher.stop)

    def put(self, alias, complete=True, partial=0):
        snapshot = prefetch.folder(alias) / 'snapshots' / 'master'; snapshot.mkdir(parents=True, exist_ok=True)
        if complete:
            (snapshot / 'config.yaml').write_text('x'); (snapshot / 'model.pt').write_bytes(b'0' * 10)
        if partial: (snapshot / 'model.pt.incomplete').write_bytes(b'0' * partial)

    def downloader(self, fail_first=0):
        calls = {'n': 0}
        def download(alias):
            calls['n'] += 1
            if calls['n'] <= fail_first: raise ConnectionError('dropped')
            self.fetched.append(alias); self.put(alias)
        return download

    def test_a_complete_cache_downloads_nothing(self):
        for alias in prefetch.ALIASES: self.put(alias)
        self.assertEqual(prefetch.missing(), [])
        self.assertFalse(prefetch.ensure_models(self.job, download=self.downloader()))
        self.assertEqual(self.fetched, [])
        self.assertFalse((self.job / 'working' / 'asr-runtime.json').exists())

    def test_only_what_is_missing_is_fetched_and_a_partial_file_does_not_count_as_present(self):
        self.put('fsmn-vad')                                     # the VAD model is already there
        self.put('paraformer-zh', complete=False, partial=538)   # 538 bytes of the big one: still missing
        self.assertEqual(prefetch.missing(), ['paraformer-zh', 'ct-punc'])
        self.assertTrue(prefetch.ensure_models(self.job, download=self.downloader()))
        self.assertEqual(self.fetched, ['paraformer-zh', 'ct-punc'])
        self.assertEqual(prefetch.missing(), [])
        self.assertFalse(prefetch.ensure_models(self.job, download=self.downloader()))   # nothing left to do a second time

    def test_progress_is_published_while_a_model_downloads(self):
        seen = []
        def slow(alias):
            for size in (100, 5000):
                self.put(alias, complete=False, partial=size); time.sleep(0.12)
                state = json.loads((self.job / 'working' / 'asr-runtime.json').read_text())
                seen.append((state['state'], state['model_index'], state['model_total'], state['downloaded_gib']))
            self.put(alias)
        for alias in ('fsmn-vad', 'ct-punc'): self.put(alias)
        prefetch.ensure_models(self.job, download=slow, interval=0.03)
        self.assertTrue(seen and all(s[0] == 'DOWNLOADING_MODELS' and (s[1], s[2]) == (1, 1) for s in seen))
        self.assertEqual(json.loads((self.job / 'working' / 'asr-runtime.json').read_text())['state'], 'MODELS_READY')

    def test_a_dropped_connection_is_retried_and_a_dead_one_gives_a_clear_message(self):
        sleeps = []
        for alias in ('fsmn-vad', 'ct-punc'): self.put(alias)
        prefetch.ensure_models(self.job, download=self.downloader(fail_first=2), sleep=sleeps.append)
        self.assertEqual((self.fetched, sleeps), (['paraformer-zh'], [3, 6]))     # two failures, backing off, then success
        shutil_target = prefetch.folder('paraformer-zh')
        import shutil; shutil.rmtree(shutil_target)
        with self.assertRaisesRegex(RuntimeError, 'Phần đã tải được giữ lại') as caught:
            prefetch.ensure_models(self.job, download=self.downloader(fail_first=99), sleep=lambda s: None)
        self.assertIsInstance(caught.exception.__cause__, ConnectionError)

    def test_cancelling_stops_before_the_next_attempt(self):
        (self.job / 'working' / 'cancel.signal').write_text(json.dumps({'mode': 'cancel'}))
        with self.assertRaises(Cancelled): prefetch.ensure_models(self.job, download=self.downloader())
        self.assertEqual(self.fetched, [])

    def test_an_incomplete_result_is_an_error_not_a_silent_success(self):
        for alias in ('fsmn-vad', 'ct-punc'): self.put(alias)
        with self.assertRaisesRegex(RuntimeError, 'tải chưa đủ'): prefetch.ensure_models(self.job, download=lambda alias: None)

    def test_the_pipeline_fetches_models_before_any_worker_and_skips_when_all_chunks_are_done(self):
        from audio_translate.transcription import pipeline
        (self.job / 'working').mkdir(exist_ok=True)
        order = []
        with patch.object(prefetch, 'ensure_models', side_effect=lambda job: order.append('models')), \
             patch('audio_translate.transcription.asr_runtime.run', side_effect=lambda *a, **k: order.append('workers')):
            pipeline.transcribe(self.job, Path('x.wav'), [{}, {}])
            self.assertEqual(order, ['models', 'workers'])
            order.clear()
            for index in (0, 1): (self.job / 'working' / f'chunk-{index:06d}.json').write_text('{}')
            pipeline.transcribe(self.job, Path('x.wav'), [{}, {}])
            self.assertEqual(order, ['workers'])                  # every chunk already done: nothing to download for


import hashlib
import io
import urllib.error

from audio_translate.translation import genius


class GatewayBundleTests(unittest.TestCase):
    """The speech models from the project's own bucket: pinned size and SHA-256, resumable, fresh links when one expires, ModelScope as the fallback."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / 'cache'
        self.job = Path(self.temp.name) / 'job'; (self.job / 'working').mkdir(parents=True)
        for patcher in (patch.dict(os.environ, {'MODELSCOPE_CACHE': str(self.cache)}),
                        patch.object(genius, 'settings', return_value={'endpoint': 'https://gateway.test'}),
                        patch.object(genius, 'credential', return_value='tok')):
            patcher.start(); self.addCleanup(patcher.stop)
        self.contents, entries = {}, []
        for alias, big in zip(prefetch.ALIASES, (b'M' * 3000, b'v' * 100, b'P' * 2000)):
            directory = prefetch.model_id(alias).replace('/', '--')
            files = []
            for relative, data in (('config.yaml', b'cfg-' + alias.encode()), ('model.pt', big), ('tokens/vocab.json', b'{}')):
                self.contents[f'{directory}/{relative}'] = data
                files.append({'path': relative, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            entries.append({'alias': alias, 'dir': directory, 'files': files})
        self.manifest = Path(self.temp.name) / 'asr-models.json'
        self.manifest.write_text(json.dumps({'version': 1, 'models': entries}), encoding='utf-8')
        patcher = patch.object(prefetch, 'manifest_path', return_value=self.manifest); patcher.start(); self.addCleanup(patcher.stop)
        self.posts, self.requests, self.expired, self.modelscope = [], [], set(), []

    def post(self, endpoint, path, body, token, timeout):
        self.posts.append((path, body['model'], list(body['paths'])))
        return {'urls': {p: f'https://signed.test/{p}' for p in body['paths']}, 'expires_in': 3600}

    def opener(self, request, timeout=0):
        url = request.full_url; key = url.split('https://signed.test/')[1]; header = request.headers.get('Range')
        self.requests.append((key, header))
        if key in self.expired:
            self.expired.discard(key); raise urllib.error.HTTPError(url, 403, 'expired', {}, None)
        offset = int(header.split('=')[1].rstrip('-')) if header else 0
        response = io.BytesIO(self.contents[key][offset:]); response.status = 206 if header else 200
        return response

    def fetch_all(self, **extra):
        return prefetch.ensure_models(self.job, download=lambda alias: self.modelscope.append(alias), post=self.post, opener=self.opener,
                                      sleep=lambda s: None, interval=0.02, **extra)

    def on_disk(self, key):
        directory, relative = key.split('/', 1)
        return self.cache / 'models' / directory / 'snapshots' / 'master' / relative

    def test_everything_comes_from_the_gateway_and_every_file_is_verified(self):
        self.assertTrue(self.fetch_all())
        for key, data in self.contents.items(): self.assertEqual(self.on_disk(key).read_bytes(), data)
        self.assertEqual(self.modelscope, [])                                   # ModelScope was not needed
        self.assertEqual([(p, m) for p, m, _ in self.posts][:1], [('/v1/model/url', 'asr-zh')])
        self.assertEqual(sorted(self.posts[0][2]), sorted(self.contents))        # one request for the whole bundle
        self.assertEqual((prefetch.missing(), prefetch.missing_files()), ([], []))
        state = json.loads((self.job / 'working' / 'asr-runtime.json').read_text())
        self.assertEqual((state['state'], state['source']), ('MODELS_READY', 'gateway'))
        self.assertFalse(list(self.cache.rglob('*.part')))
        self.assertFalse(self.fetch_all())                                             # a second run finds everything and asks for nothing

    def test_a_partial_file_resumes_with_a_range_request(self):
        key = prefetch.model_id('paraformer-zh').replace('/', '--') + '/model.pt'
        part = self.on_disk(key).with_name('model.pt.part'); part.parent.mkdir(parents=True)
        part.write_bytes(self.contents[key][:1200])
        self.fetch_all()
        self.assertIn((key, 'bytes=1200-'), self.requests)
        self.assertEqual(self.on_disk(key).read_bytes(), self.contents[key])

    def test_an_expired_link_is_replaced_by_a_fresh_one(self):
        self.expired.add(prefetch.model_id('ct-punc').replace('/', '--') + '/model.pt')
        self.fetch_all()
        self.assertEqual(len(self.posts), 2)                                    # a second request for links after the 403
        self.assertEqual(prefetch.missing_files(), [])

    def test_a_wrong_file_is_never_kept_and_modelscope_takes_over(self):
        key = prefetch.model_id('paraformer-zh').replace('/', '--') + '/model.pt'
        self.contents[key] = b'X' * 3000                                         # same size, other bytes: the pinned SHA-256 will not match
        try: self.fetch_all()
        except RuntimeError: pass                                                # the fake ModelScope adds nothing, so it ends as an incomplete result
        self.assertFalse(self.on_disk(key).exists())
        self.assertFalse(list(self.cache.rglob('*.part')))
        self.assertIn('paraformer-zh', self.modelscope)

    def test_an_unreachable_gateway_falls_back_to_modelscope(self):
        def down(*args): raise genius.GatewayError(0, 'UNREACHABLE')
        with self.assertRaisesRegex(RuntimeError, 'tải chưa đủ'):
            prefetch.ensure_models(self.job, download=lambda alias: self.modelscope.append(alias), post=down, opener=self.opener, sleep=lambda s: None, interval=0.02)
        self.assertEqual(self.modelscope, list(prefetch.ALIASES))

    def test_complete_files_are_not_requested_again(self):
        self.fetch_all()
        self.requests.clear(); self.posts.clear()
        victim = next(self.cache.rglob('model.pt')); victim.unlink()
        self.fetch_all()
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0][2], [victim.parents[2].name + '/model.pt'])   # just the lost file

    def test_no_published_bundle_means_modelscope_only(self):
        self.manifest.write_text(json.dumps({'version': 1, 'models': []}), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'tải chưa đủ'):
            self.fetch_all()
        self.assertEqual((self.posts, self.modelscope), ([], list(prefetch.ALIASES)))

if __name__ == '__main__':
    unittest.main()
