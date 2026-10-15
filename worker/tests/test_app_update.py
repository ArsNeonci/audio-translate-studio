"""App updates (api/app_update.py): what the app trusts, what it offers, how it downloads and checks a package, and how it hands over to updater.exe."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from audio_translate.api import app_update as up

PRODUCT = 'audio-translate-plus'
RUNTIME = 'a' * 64


def package_bytes(version='3.2.1', product=PRODUCT, runtime=RUNTIME, extra=(), missing=()):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        files = {'app/licensing/public-config.json': json.dumps({'product_id': product, 'version': version, 'scheme': 's'}),
                 'app/runtime-fingerprint.json': json.dumps({'sha256': runtime}), 'AudioTranslate.exe': 'shell', 'updater.exe': 'updater',
                 'app/security-core/bin/audio-security-core.exe': 'core', 'app/worker/x.py': 'print(1)'}
        for name, text in files.items():
            if name not in missing: z.writestr(name, text)
        for name in extra: z.writestr(name, 'x')
    return out.getvalue()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.private = Ed25519PrivateKey.generate()
        self.keys = [self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)]
        for target, value in (('DATA', self.base / 'data'), ('ROOT', self.base / 'install' / 'app')):
            p = patch.object(up, target, value); p.start(); self.addCleanup(p.stop)
        (self.base / 'install' / 'app').mkdir(parents=True); (self.base / 'install' / 'AudioTranslate.exe').write_text('x'); (self.base / 'install' / 'updater.exe').write_text('x')
        (self.base / 'install' / 'app' / 'runtime-fingerprint.json').write_text(json.dumps({'sha256': RUNTIME}))
        (self.base / 'install' / 'app' / 'licensing').mkdir()
        (self.base / 'install' / 'app' / 'licensing' / 'public-config.json').write_text(json.dumps({'product_id': PRODUCT, 'version': '3.2.0'}))
        for target, value in (('public_keys', lambda: self.keys), ('installed_version', lambda: '3.2.0')):
            p = patch.object(up, target, value); p.start(); self.addCleanup(p.stop)
        self.zip = package_bytes()
        self.installer = b'MZ' + b'0' * 5000

    def manifest(self, **changes):
        v = changes.get('version', '3.2.1')
        data = {'schema': 1, 'product': PRODUCT, 'channel': 'stable', 'serial': 5, 'version': v, 'released_at': '2026-10-15T00:00:00Z', 'notes': {'vi': 'Mới', 'en': 'New'},
                'runtime_sha256': RUNTIME, 'min_version': None, 'allow_downgrade': False,
                'packages': [{'kind': 'app', 'path': f'updates/{PRODUCT}/{v}/AudioTranslate-Plus-{v}-app.zip', 'size': len(self.zip), 'sha256': hashlib.sha256(self.zip).hexdigest()},
                             {'kind': 'installer', 'path': f'updates/{PRODUCT}/{v}/AudioTranslate-Plus-{v}.exe', 'size': len(self.installer), 'sha256': hashlib.sha256(self.installer).hexdigest()}]}
        data.update(changes)
        return data

    def signed(self, data, key=None):
        raw = json.dumps(data, sort_keys=True).encode()
        return raw, base64.b64encode((key or self.private).sign(raw)).decode()

    def reply(self, data=None, urls=True, key=None):
        raw, sig = self.signed(data or self.manifest(), key)
        return {'manifest': raw.decode(), 'signature': sig, 'urls': {p['path']: f"https://x.example/{p['path']}" for p in json.loads(raw)['packages']} if urls else {}}

    # --- trust ---------------------------------------------------------------------------------------------------------------------
    def test_a_valid_signed_manifest_for_this_product_is_accepted(self):
        raw, sig = self.signed(self.manifest())
        data = up.verify(raw, sig, product=PRODUCT)
        self.assertEqual((data['version'], data['serial']), ('3.2.1', 5))

    def test_everything_else_is_refused(self):
        raw, sig = self.signed(self.manifest())
        other = Ed25519PrivateKey.generate()
        cases = {'unknown key': (raw, base64.b64encode(other.sign(raw)).decode()), 'tampered': (raw.replace(b'3.2.1', b'9.9.9'), sig), 'not base64': (raw, '***'),
                 'too big': (b'{' + b' ' * 70000 + b'}', sig)}
        for name, (r, s) in cases.items():
            with self.assertRaises(up.ManifestError, msg=name): up.verify(r, s, product=PRODUCT)
        bad = {'another product': {'product': 'audio-translate-basic'}, 'another channel': {'channel': 'test'}, 'no serial': {'serial': 0}, 'schema': {'schema': 2},
               'version': {'version': 'latest'}, 'runtime': {'runtime_sha256': 'xyz'}, 'min version': {'min_version': 'new'}, 'downgrade flag': {'allow_downgrade': 'yes'},
               'notes': {'notes': {'vi': 'x' * 5000}}, 'no packages': {'packages': []}}
        for name, change in bad.items():
            with self.assertRaises(up.ManifestError, msg=name): up.verify(*self.signed(self.manifest(**change)), product=PRODUCT)
        m = self.manifest()
        paths = {'another edition': ('path', f'updates/audio-translate-basic/3.2.1/AudioTranslate-Plus-3.2.1-app.zip'), 'another version': ('path', f'updates/{PRODUCT}/3.9.9/a-app.zip'),
                 'traversal': ('path', f'updates/{PRODUCT}/3.2.1/../../x.zip'), 'wrong extension': ('path', f'updates/{PRODUCT}/3.2.1/a-app.exe'),
                 'too large': ('size', 600 * 1024 ** 2), 'hash': ('sha256', 'z' * 64)}
        for name, (field, value) in paths.items():
            data = json.loads(json.dumps(m)); data['packages'][0][field] = value
            with self.assertRaises(up.ManifestError, msg=name): up.verify(*self.signed(data), product=PRODUCT)
        twice = json.loads(json.dumps(m)); twice['packages'][1]['kind'] = 'app'
        with self.assertRaises(up.ManifestError): up.verify(*self.signed(twice), product=PRODUCT)

    # --- asking the gateway ---------------------------------------------------------------------------------------------------------
    def test_a_check_stores_the_verified_manifest_and_is_not_repeated_until_due(self):
        calls = []
        def post(endpoint, path, body, token, timeout): calls.append((path, body)); return self.reply()
        with patch('audio_translate.translation.genius.settings', lambda: {'endpoint': 'https://gw.example'}), patch('audio_translate.translation.genius.credential', lambda: 'tok'):
            first = up.check(post=post, now=1000.0)
            self.assertEqual((first, calls), ({'changed': True, 'error': None}, [('/v1/app/update', {'channel': 'stable'})]))
            self.assertEqual(up.local_manifest()['version'], '3.2.1')
            up.check(post=post, now=1000.0 + 60)                                       # not due: no second call
            self.assertEqual(len(calls), 1)
            up.check(force=True, post=post, now=1000.0 + 60)                           # the Settings button
            self.assertEqual(len(calls), 2)
            up.check(force=True, post=post, now=1000.0 + 61)                           # but not again within the gap
            self.assertEqual(len(calls), 2)
            self.assertEqual(up.check(post=post, now=1000.0 + 7 * 3600)['changed'], False)   # due again; the same serial is not a change
            self.assertEqual(len(calls), 3)

    def test_an_older_serial_a_bad_signature_and_an_unreachable_gateway_change_nothing(self):
        with patch('audio_translate.translation.genius.settings', lambda: {'endpoint': 'https://gw.example'}), patch('audio_translate.translation.genius.credential', lambda: 'tok'):
            up.check(post=lambda *a: self.reply(), now=1000.0)
            old = up.check(force=True, post=lambda *a: self.reply(self.manifest(serial=4, version='3.2.9')), now=2000.0)
            self.assertEqual(old['error'], 'MANIFEST_older serial'); self.assertEqual(up.local_manifest()['serial'], 5)     # no rollback by replaying an old manifest
            forged = up.check(force=True, post=lambda *a: self.reply(self.manifest(serial=9), key=Ed25519PrivateKey.generate()), now=3000.0)
            self.assertEqual(forged['error'], 'MANIFEST_signature'); self.assertEqual(up.local_manifest()['serial'], 5)
            def down(*a): raise type('GatewayError', (Exception,), {'code': 'UNREACHABLE'})()
            self.assertEqual(up.check(force=True, post=down, now=4000.0), {'changed': False, 'error': 'UNREACHABLE'})
            newer = up.check(force=True, post=lambda *a: self.reply(self.manifest(serial=6, version='3.2.2')), now=5000.0)     # but a newer one is taken
            self.assertTrue(newer['changed'])
        with patch('audio_translate.translation.genius.settings', lambda: {}):
            self.assertEqual(up.check(force=True, now=9000.0)['error'], 'RuntimeError: NO_GATEWAY')                       # never raises

    # --- what is offered -------------------------------------------------------------------------------------------------------------
    def store(self, **changes):
        raw, sig = self.signed(self.manifest(**changes))
        up.root().mkdir(parents=True, exist_ok=True)
        (up.root() / 'manifest.json').write_bytes(raw); (up.root() / 'manifest.sig').write_text(sig, encoding='ascii')

    def test_only_a_newer_release_is_offered_and_the_kind_follows_the_runtime(self):
        self.store()
        wanted = up.offer()
        self.assertEqual((wanted['version'], wanted['kind'], wanted['required'], wanted['failed_before']), ('3.2.1', 'app', False, False))
        self.assertEqual(wanted['size'], len(self.zip))
        self.store(runtime_sha256='b' * 64)                                                  # the runtime changed: the full installer
        self.assertEqual(up.offer()['kind'], 'installer')
        self.store(version='3.2.0')
        self.assertIsNone(up.offer())                                                         # the same version is not an update
        for older in ('3.1.9', '2.9.9'):
            self.store(version=older); self.assertIsNone(up.offer(), older)
        self.store(version='3.1.9', allow_downgrade=True)
        self.assertTrue(up.offer()['downgrade'])                                              # a roll back the owner asked for
        self.store(min_version='3.2.1'); self.assertTrue(up.offer()['required'])             # an old release the owner wants updated
        self.store(min_version='3.1.0'); self.assertFalse(up.offer()['required'])
        (up.root() / 'failed-versions.json').write_text('["3.2.1"]'); self.assertTrue(up.offer()['failed_before'])
        with patch.object(up, 'installed_version', lambda: None): self.assertIsNone(up.offer())   # a development checkout has no version: nothing to update
        with patch.object(up, 'install_root', lambda: None): self.assertEqual(up.offer()['kind'], 'installer')   # not an installed copy: no app package

    # --- downloading -----------------------------------------------------------------------------------------------------------------
    class Opener:
        def __init__(self, blobs): self.blobs, self.asked = blobs, []
        def __call__(self, request, timeout=60):
            url = request.full_url; self.asked.append((url, request.headers.get('Range')))
            blob = next(b for path, b in self.blobs.items() if url.endswith(path))
            start = int((request.headers.get('Range') or 'bytes=0-').split('=')[1].rstrip('-'))
            body = io.BytesIO(blob[start:]); body.status = 206 if start else 200
            body.__enter__ = lambda s=body: s; body.__exit__ = lambda *a: None
            return body

    def download(self, zip_bytes=None, **changes):
        zip_bytes = zip_bytes if zip_bytes is not None else self.zip
        manifest = self.manifest(**changes)
        manifest['packages'][0].update(size=len(zip_bytes), sha256=hashlib.sha256(zip_bytes).hexdigest())
        raw, sig = self.signed(manifest)
        reply = {'manifest': raw.decode(), 'signature': sig, 'urls': {p['path']: f"https://x.example/{p['path']}" for p in manifest['packages']}}
        opener = self.Opener({manifest['packages'][0]['path']: zip_bytes, manifest['packages'][1]['path']: self.installer})
        with patch('audio_translate.translation.genius.settings', lambda: {'endpoint': 'https://gw.example'}), patch('audio_translate.translation.genius.credential', lambda: 'tok'):
            up.check(post=lambda *a: reply, now=time.time() - 10_000)
            self.assertTrue(up.start_download(post=lambda *a: reply, opener=opener))
            for _ in range(200):
                if up.download_state()['state'] != 'downloading': break
                time.sleep(0.05)
        return up.download_state(), opener

    def test_the_app_package_is_downloaded_checked_and_ready(self):
        state, opener = self.download()
        self.assertEqual((state['state'], state['error']), ('ready', None))
        marker = up.ready()
        self.assertEqual((marker['version'], marker['kind'], marker['from_version']), ('3.2.1', 'app', '3.2.0'))
        self.assertEqual(Path(marker['package']).read_bytes(), self.zip)
        status = up.status()
        self.assertEqual((status['ready'], status['download']['state'], status['offer']['version']), (True, 'ready', '3.2.1'))
        # After a restart (no download in memory) it is still ready; after the installed version changes it is not.
        up._download.update(state='idle')
        self.assertTrue(up.status()['ready'])
        with patch.object(up, 'installed_version', lambda: '3.2.1'): self.assertFalse(up.status()['ready']); self.assertIsNone(up.status()['offer'])

    def test_a_package_with_the_right_hash_but_the_wrong_content_is_never_ready(self):
        # Signed and intact, yet not something updater.exe may apply here.
        cases = {'the runtime inside': package_bytes(extra=['runtime/python/python.exe']), 'another release': package_bytes(version='3.9.9'),
                 'another product': package_bytes(product='audio-translate-basic'), 'another runtime': package_bytes(runtime='c' * 64),
                 'no updater': package_bytes(missing=['updater.exe']), 'a path that leaves the folder': package_bytes(extra=['app/../../evil.txt'])}
        for name, blob in cases.items():
            up._download.update(state='idle')
            state, _ = self.download(zip_bytes=blob)
            self.assertEqual(state['state'], 'failed', name); self.assertIsNone(up.ready(), name)

    def test_a_download_that_does_not_match_its_signed_hash_is_deleted(self):
        manifest = self.manifest(); good = hashlib.sha256(self.zip).hexdigest()
        manifest['packages'][0].update(size=len(self.zip), sha256=good)
        raw, sig = self.signed(manifest)
        reply = {'manifest': raw.decode(), 'signature': sig, 'urls': {p['path']: f"https://x.example/{p['path']}" for p in manifest['packages']}}
        tampered = bytearray(self.zip); tampered[100] ^= 0xFF
        opener = self.Opener({manifest['packages'][0]['path']: bytes(tampered), manifest['packages'][1]['path']: self.installer})
        with patch('audio_translate.translation.genius.settings', lambda: {'endpoint': 'https://gw.example'}), patch('audio_translate.translation.genius.credential', lambda: 'tok'):
            up.check(post=lambda *a: reply, now=time.time() - 10_000)
            up.start_download(post=lambda *a: reply, opener=opener)
            for _ in range(200):
                if up.download_state()['state'] != 'downloading': break
                time.sleep(0.05)
        self.assertEqual(up.download_state()['state'], 'failed'); self.assertIn('CHECKSUM', up.download_state()['error'])
        self.assertEqual(list(up.pending_dir().glob('*.zip*')), []); self.assertIsNone(up.ready())

    def test_a_partial_download_continues_where_it_stopped(self):
        manifest = self.manifest(); manifest['packages'][0].update(size=len(self.zip), sha256=hashlib.sha256(self.zip).hexdigest())
        up.pending_dir().mkdir(parents=True)
        (up.pending_dir() / 'AudioTranslate-Plus-3.2.1-app.zip.part').write_bytes(self.zip[:300])
        state, opener = self.download()
        self.assertEqual(state['state'], 'ready')
        self.assertTrue(any(range_ == 'bytes=300-' for _, range_ in opener.asked))                  # only the rest was asked for

    def test_nothing_is_downloaded_when_there_is_no_update(self):
        self.assertFalse(up.start_download())
        self.store(version='3.2.0')
        self.assertFalse(up.start_download())

    # --- handing over to updater.exe ---------------------------------------------------------------------------------------------------
    def test_the_plan_names_the_verified_package_and_the_installation(self):
        self.download()
        marker = up.ready()
        plan = up.write_plan(marker)
        written = json.loads((up.root() / 'apply.json').read_text())
        self.assertEqual(written, plan)
        self.assertEqual((plan['kind'], plan['version'], plan['from_version'], plan['sha256'], plan['install_root'], plan['data']),
                         ('app', '3.2.1', '3.2.0', marker['sha256'], str(self.base / 'install'), str(self.base / 'data')))
        with patch.object(up, 'install_root', lambda: None):
            with self.assertRaises(up.ManifestError): up.write_plan(marker)                            # a development checkout cannot apply anything

    def test_the_health_marker_and_the_last_result(self):
        up.write_health()
        health = json.loads((up.root() / 'health.json').read_text())
        self.assertEqual(health['version'], '3.2.0')
        (up.root() / 'last-update.json').write_text(json.dumps({'ok': False, 'version': '3.2.1', 'from': '3.2.0', 'error': 'x', 'at': 't1'}))
        self.assertEqual(up.last_result()['ok'], False)
        up.acknowledge(); self.assertIsNone(up.last_result())                                         # seen
        (up.root() / 'last-update.json').write_text(json.dumps({'ok': True, 'version': '3.2.2', 'from': '3.2.1', 'error': '', 'at': 't2'}))
        self.assertEqual(up.last_result()['version'], '3.2.2')                                        # a later result shows again

    def test_the_channel_comes_from_the_environment_and_is_checked(self):
        with patch.dict('os.environ', {'AUDIO_UPDATE_CHANNEL': 'test'}): self.assertEqual(up.channel(), 'test')
        with patch.dict('os.environ', {'AUDIO_UPDATE_CHANNEL': '../x'}): self.assertEqual(up.channel(), 'stable')
        with patch.dict('os.environ', {}, clear=False): self.assertEqual(up.channel(), 'stable')


if __name__ == '__main__':
    unittest.main()
