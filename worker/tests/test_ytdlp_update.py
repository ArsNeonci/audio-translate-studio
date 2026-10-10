"""The signed yt-dlp update channel: only a manifest signed by a pinned key, with matching wheels, ever changes what runs."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from audio_translate.transcription import ytdlp_update as update


def wheel(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, text in files.items(): archive.writestr(name, text)
    return buffer.getvalue()


class Response(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        patch.object(update, 'DATA', Path(self.temp.name)).start()
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        patch.object(update, 'public_keys', return_value=[public]).start()
        patch('audio_translate.translation.genius.settings', return_value={'endpoint': 'https://api.test'}).start()
        patch('audio_translate.translation.genius.credential', return_value='LIC').start()
        self.addCleanup(patch.stopall)
        self.files = {'youtube/yt_dlp-2099.1.1-py3-none-any.whl': wheel({'yt_dlp/__init__.py': "MARK = 'from-gateway'\n"}),
                      'youtube/yt_dlp_ejs-9.0.0-py3-none-any.whl': wheel({'yt_dlp_ejs/__init__.py': ''})}
        self.served, self.posts = dict(self.files), []

    def manifest(self, serial=10, attempts=None, files=None, **extra):
        files = files or self.files
        packages = [{'name': 'yt-dlp' if '/yt_dlp-' in path else 'yt-dlp-ejs', 'version': path.split('-')[1], 'path': path,
                     'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for path, data in files.items()]
        body = {'schema': 1, 'serial': serial, 'packages': packages, 'check_hours': 6,
                'attempts': attempts or [{'client': 'mweb', 'cookies': False}, {'client': None, 'cookies': True}], **extra}
        raw = json.dumps(body).encode()
        return raw, base64.b64encode(self.key.sign(raw)).decode()

    def post_for(self, raw, signature):
        def post(endpoint, path, body, token, timeout):
            self.posts.append((endpoint, path, body, token))
            return {'manifest': raw.decode(), 'signature': signature, 'urls': {p: f'https://storage.test/{p}' for p in self.files}}
        return post

    def opener(self, request, timeout):
        self.opened = getattr(self, 'opened', 0) + 1
        return Response(self.served[request.full_url.split('storage.test/', 1)[1]])

    def test_a_signed_release_is_installed_and_used_before_the_bundled_one(self):
        raw, sig = self.manifest()
        result = update.refresh(post=self.post_for(raw, sig), opener=self.opener, now=1000)
        self.assertEqual(result, {'changed': True, 'serial': 10, 'error': None})
        self.assertEqual(self.posts[0][1:], ('/v1/youtube/update', {'serial': None}, 'LIC'))
        self.assertEqual(update.attempts(), [{'client': 'mweb', 'cookies': False}, {'client': None, 'cookies': True}])
        self.assertEqual(update.info()['source'], 'gateway'); self.assertEqual(update.info()['version'], '2099.1.1')
        with patch.object(sys, 'path', list(sys.path)), patch.dict(sys.modules):
            sys.modules.pop('yt_dlp', None)
            self.assertEqual(update.activate(), '2099.1.1')
            self.assertEqual(sys.path[0], str(update.release_dir(10)))
            import yt_dlp
            self.assertEqual(yt_dlp.MARK, 'from-gateway')

    def test_nothing_changes_without_a_valid_signature_or_matching_wheels(self):
        raw, sig = self.manifest()
        other = Ed25519PrivateKey.generate()
        forged = base64.b64encode(other.sign(raw)).decode()
        self.assertEqual(update.refresh(post=self.post_for(raw, forged), opener=self.opener, now=1000)['error'], 'MANIFEST_signature')
        tampered = raw.replace(b'"serial": 10', b'"serial": 11')
        self.assertEqual(update.refresh(force=True, post=self.post_for(tampered, sig), opener=self.opener, now=2000)['error'], 'MANIFEST_signature')
        self.served['youtube/yt_dlp-2099.1.1-py3-none-any.whl'] = b'x' * len(self.files['youtube/yt_dlp-2099.1.1-py3-none-any.whl'])   # same size, other bytes
        self.assertIn('CHECKSUM_MISMATCH', update.refresh(force=True, post=self.post_for(raw, sig), opener=self.opener, now=4000)['error'])
        self.assertIsNone(update.local_manifest())
        self.assertFalse((update.root() / 'releases' / '10').exists())
        self.assertEqual(update.info()['source'], 'bundled')
        self.assertEqual(update.attempts(), [dict(s) for s in update.DEFAULT_ATTEMPTS])
        with patch.object(sys, 'path', list(sys.path)): self.assertIsNone(update.activate())

    def test_checks_are_spaced_and_a_forced_check_is_rate_limited(self):
        raw, sig = self.manifest()
        post = self.post_for(raw, sig)
        update.refresh(post=post, opener=self.opener, now=1000)
        update.refresh(post=post, opener=self.opener, now=1000 + 5 * 3600)          # not due: 6 hours
        update.refresh(force=True, post=post, opener=self.opener, now=1000 + 5 * 3600)   # forced: allowed once
        update.refresh(force=True, post=post, opener=self.opener, now=1000 + 5 * 3600 + 60)   # forced again within 15 minutes: no
        self.assertEqual(len(self.posts), 2)
        opened = self.opened
        self.assertEqual(update.refresh(post=post, opener=self.opener, now=1000 + 12 * 3600)['changed'], False)   # same serial: nothing fetched
        self.assertEqual((len(self.posts), self.opened), (3, opened))

    def test_an_older_manifest_cannot_roll_back_and_a_new_one_replaces_the_old_release(self):
        update.refresh(post=self.post_for(*self.manifest(serial=10)), opener=self.opener, now=1000)
        self.assertEqual(update.refresh(force=True, post=self.post_for(*self.manifest(serial=9)), opener=self.opener, now=9000)['error'], 'MANIFEST_older serial')
        self.assertEqual(update.info()['serial'], 10)
        update.refresh(force=True, post=self.post_for(*self.manifest(serial=11, attempts=[{'client': 'tv', 'cookies': True}])), opener=self.opener, now=20000)
        update.refresh(force=True, post=self.post_for(*self.manifest(serial=12)), opener=self.opener, now=40000)
        self.assertEqual(update.info()['serial'], 12)
        self.assertEqual(sorted(p.name for p in (update.root() / 'releases').iterdir()), ['11', '12'])   # the previous one is kept, older ones go

    def test_a_failed_check_is_recorded_and_retried_within_an_hour(self):
        def down(*args): raise type('GatewayError', (Exception,), {'code': 'UNREACHABLE'})()
        self.assertEqual(update.refresh(post=down, now=1000)['error'], 'UNREACHABLE')
        checked = json.loads((update.root() / 'checked.json').read_text(encoding='utf-8'))
        self.assertEqual((checked['error'], checked['next_at']), ('UNREACHABLE', 1000 + 3600))
        self.assertEqual(update.info()['error'], 'UNREACHABLE')

    def test_manifest_fields_are_bounded(self):
        bad = [
            {'files': {'youtube/requests-9-py3-none-any.whl': wheel({'requests/__init__.py': ''})}},   # not an allowed package
            {'attempts': [{'client': 'tv; rm', 'cookies': False}]},
            {'attempts': [{'client': 'tv', 'cookies': 'yes'}]},
            {'check_hours': 0},
        ]
        for change in bad:
            with self.subTest(change=change):
                raw, sig = self.manifest(**change)
                with self.assertRaises(update.ManifestError): update.verify(raw, sig)
        evil = {'youtube/yt_dlp-2099.1.1-py3-none-any.whl': wheel({'../../outside.py': 'x'})}
        self.files = self.served = evil
        raw, sig = self.manifest(files=evil)
        self.assertEqual(update.refresh(post=self.post_for(raw, sig), opener=self.opener, now=1000)['error'], 'MANIFEST_unsafe wheel entry')
        self.assertFalse((Path(self.temp.name).parent / 'outside.py').exists())


if __name__ == '__main__':
    unittest.main()
