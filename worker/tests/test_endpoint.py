"""The signed address file (core/endpoint.py): what the app trusts, how it keeps the newest copy, and how a call that fails at network level finds
a server that has moved. Synthetic keys; no network (urlopen is replaced by a fake that serves the mirrors and the servers)."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from audio_translate.api import billing, license as lease
from audio_translate.core import endpoint
from audio_translate.translation import genius

PLACES = ['https://owner.github.io/address', 'https://address.pages.dev']
OLD_GATEWAY, NEW_GATEWAY = 'https://gateway.old.example', 'https://gateway.new.example'
OLD_BILLING, NEW_BILLING = 'https://billing.old.example', 'https://billing.new.example'


def public_of(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def signed(key, serial=1, gateway=OLD_GATEWAY, billing_url=OLD_BILLING, **override):
    data = {'schema': endpoint.SCHEMA, 'serial': serial, 'gateway': gateway, 'billing': billing_url, **override}
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode()
    return raw, base64.b64encode(key.sign(raw)).decode()


class Reply(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class Network:
    """A fake urlopen: mirrors serve files, servers answer JSON or are down."""
    def __init__(self): self.files, self.down, self.calls, self.server_reply = {}, set(), [], {'ok': True}

    def serve(self, place, raw, signature):
        self.files[place + '/endpoint.json'], self.files[place + '/endpoint.json.sig'] = raw, signature.encode() + b'\n'

    def __call__(self, request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        self.calls.append(url)
        origin = '/'.join(url.split('/')[:3])
        if url in self.files: return Reply(self.files[url])
        if any(origin == place.rsplit('/', 1)[0] or url.startswith(place) for place in PLACES) and url not in self.files:
            raise urllib.error.HTTPError(url, 404, 'missing', {}, io.BytesIO(b''))
        if origin in self.down: raise urllib.error.URLError('name not resolved')
        return Reply(json.dumps(self.server_reply).encode())


class EndpointCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.key = Ed25519PrivateKey.generate()
        self.net = Network()
        config = Path(self.temp.name) / 'genius.json'
        config.write_text(json.dumps({'endpoint': OLD_GATEWAY, 'billing_url': OLD_BILLING, 'directory': PLACES}), encoding='utf-8')
        for target, value in ((endpoint, ('DATA', Path(self.temp.name) / 'data')), ):
            patcher = patch.object(target, *value); patcher.start(); self.addCleanup(patcher.stop)
        for patcher in (patch.object(endpoint, '_config_path', lambda: config), patch.object(endpoint, 'public_keys', lambda: [public_of(self.key)]),
                        patch.dict(os.environ, {'AUDIO_ENDPOINT_MIRRORS': ','.join(PLACES)}), patch('urllib.request.urlopen', self.net),
                        patch.object(genius, 'CONFIG', config), patch.object(billing, 'FILE', Path(self.temp.name) / 'billing.json')):
            patcher.start(); self.addCleanup(patcher.stop)
        endpoint._state.update(failure_at=-endpoint.FAILURE_GAP, memo=None)

    def publish(self, serial=1, places=PLACES, **kw):
        raw, signature = signed(self.key, serial, **kw)
        for place in places: self.net.serve(place, raw, signature)
        return raw, signature


class VerifyTests(EndpointCase):
    def test_a_file_signed_by_a_pinned_key_is_accepted(self):
        raw, signature = signed(self.key)
        self.assertEqual(endpoint.verify(raw, signature)['gateway'], OLD_GATEWAY)

    def test_everything_else_is_refused(self):
        raw, signature = signed(self.key)
        other = Ed25519PrivateKey.generate()
        cases = {'another key': signed(other), 'tampered': (raw.replace(b'old', b'bad'), signature), 'not base64': (raw, '###'), 'empty signature': (raw, ''),
                 'wrong schema': signed(self.key, schema='audio-endpoint-v2'), 'serial 0': signed(self.key, 0), 'serial true': signed(self.key, True),
                 'serial text': signed(self.key, '5'), 'http address': signed(self.key, gateway='http://gateway.example'),
                 'a path after the host': signed(self.key, gateway='https://gateway.example/v1'), 'a user in the address': signed(self.key, gateway='https://a@b.example'),
                 'no dot in the host': signed(self.key, gateway='https://localhost'), 'upper case': signed(self.key, gateway='https://Gateway.example'),
                 'big': (b' ' * (endpoint.MAX_BYTES + 1), signature)}
        for name, (body, sig) in cases.items():
            with self.assertRaises(endpoint.EndpointError, msg=name): endpoint.verify(body, sig)

    def test_the_loopback_is_allowed_for_development_only_with_a_signature(self):
        raw, signature = signed(self.key, gateway='http://127.0.0.1:8790')
        self.assertEqual(endpoint.verify(raw, signature)['gateway'], 'http://127.0.0.1:8790')
        self.assertRaises(endpoint.EndpointError, endpoint.verify, *signed(Ed25519PrivateKey.generate(), gateway='http://127.0.0.1:8790'))

    def test_no_pinned_key_means_nothing_is_trusted(self):
        with patch.object(endpoint, 'public_keys', lambda: []): self.assertRaises(endpoint.EndpointError, endpoint.verify, *signed(self.key))


class RefreshTests(EndpointCase):
    def test_without_a_signed_file_the_shipped_addresses_are_used(self):
        self.assertEqual((endpoint.address('endpoint'), endpoint.address('billing_url'), endpoint.current()), (OLD_GATEWAY, OLD_BILLING, None))
        self.assertEqual(genius.settings()['endpoint'], OLD_GATEWAY)

    def test_the_first_read_is_kept_and_wins_over_the_shipped_address(self):
        self.publish(1, gateway=NEW_GATEWAY, billing_url=NEW_BILLING)
        self.assertEqual(endpoint.refresh(), {'changed': True, 'serial': 1, 'error': None})
        self.assertEqual((endpoint.address('endpoint'), endpoint.address('billing_url')), (NEW_GATEWAY, NEW_BILLING))
        self.assertEqual((genius.settings()['endpoint'], genius.settings()['billing_url'], lease.gateway_endpoint(), lease.billing_url()), (NEW_GATEWAY, NEW_BILLING, NEW_GATEWAY, NEW_BILLING))
        self.assertEqual(endpoint.refresh()['changed'], False)   # the same serial again changes nothing

    def test_an_older_copy_never_replaces_a_newer_one(self):
        self.publish(5, gateway=NEW_GATEWAY); endpoint.refresh()
        self.publish(3, gateway=OLD_GATEWAY)   # a mirror that lags, or an old file replayed
        self.assertEqual(endpoint.refresh()['error'], 'OLDER_SERIAL')
        self.assertEqual(endpoint.address('endpoint'), NEW_GATEWAY)

    def test_the_newest_copy_among_the_places_wins(self):
        self.publish(1, [PLACES[0]], gateway=OLD_GATEWAY); self.publish(2, [PLACES[1]], gateway=NEW_GATEWAY)
        endpoint.refresh()
        self.assertEqual((endpoint.cached('gateway'), endpoint.current()['serial']), (NEW_GATEWAY, 2))

    def test_a_place_that_is_down_or_holds_a_bad_file_does_not_stop_the_others(self):
        self.net.files.clear()
        bad = signed(Ed25519PrivateKey.generate(), 9, gateway='https://evil.example')   # signed by someone else
        self.net.serve(PLACES[0], *bad)
        self.publish(2, [PLACES[1]], gateway=NEW_GATEWAY)
        self.assertEqual(endpoint.refresh()['serial'], 2)
        self.assertEqual(endpoint.address('endpoint'), NEW_GATEWAY)

    def test_nothing_reachable_keeps_what_the_app_had(self):
        self.publish(4, gateway=NEW_GATEWAY); endpoint.refresh()
        self.net.files.clear()
        self.assertEqual(endpoint.refresh(), {'changed': False, 'serial': 4, 'error': 'UNREACHABLE'})
        self.assertEqual(endpoint.address('endpoint'), NEW_GATEWAY)

    def test_the_saved_file_is_checked_again_so_an_edited_copy_counts_for_nothing(self):
        self.publish(1, gateway=NEW_GATEWAY); endpoint.refresh()
        path = endpoint.folder() / 'directory.json'
        saved = json.loads(path.read_text(encoding='utf-8'))
        saved['manifest'] = saved['manifest'].replace('gateway.new', 'gateway.evil'); path.write_text(json.dumps(saved), encoding='utf-8')
        self.assertIsNone(endpoint.current()); self.assertEqual(endpoint.address('endpoint'), OLD_GATEWAY)
        path.write_text('not json', encoding='utf-8'); self.assertIsNone(endpoint.current())

    def test_no_directory_means_nothing_is_asked(self):
        with patch.dict(os.environ, {'AUDIO_ENDPOINT_MIRRORS': ''}):
            self.assertEqual(endpoint.refresh()['error'], 'NO_DIRECTORY'); self.assertIsNone(endpoint.failover(OLD_GATEWAY)); endpoint.refresh_in_background()
        self.assertEqual(self.net.calls, [])

    def test_only_https_places_are_used_and_the_nothing_sent_is_a_plain_get(self):
        with patch.dict(os.environ, {'AUDIO_ENDPOINT_MIRRORS': 'http://plain.example, https://ok.example/, ftp://x'}):
            self.assertEqual(endpoint.mirrors(), ['https://ok.example'])
        self.publish(1); endpoint.refresh()
        for url in self.net.calls: self.assertTrue(url.endswith(('endpoint.json', 'endpoint.json.sig')), url)

    def test_stale_after_a_day(self):
        self.assertTrue(endpoint.stale()); self.publish(1); endpoint.refresh(now=1000.0)
        self.assertFalse(endpoint.stale(now=1000.0 + 3600)); self.assertTrue(endpoint.stale(now=1000.0 + endpoint.STALE_SECONDS + 1))


class FailoverTests(EndpointCase):
    def test_a_moved_gateway_is_found_and_the_call_is_sent_again(self):
        self.net.down.add(OLD_GATEWAY); self.publish(1, gateway=NEW_GATEWAY, billing_url=NEW_BILLING)
        self.net.server_reply = {'urls': {'a': 'b'}}
        reply = genius.post(OLD_GATEWAY, '/v1/model/url', {'model': 'm'}, 'token', 5)
        self.assertEqual(reply, {'urls': {'a': 'b'}})
        called = [u for u in self.net.calls if u.startswith('https://gateway')]
        self.assertEqual(called, [OLD_GATEWAY + '/v1/model/url', NEW_GATEWAY + '/v1/model/url'])
        self.assertEqual(endpoint.address('endpoint'), NEW_GATEWAY)   # and the next calls go straight there

    def test_get_and_the_licence_calls_find_it_too(self):
        self.net.down.add(OLD_GATEWAY); self.publish(1, gateway=NEW_GATEWAY)
        self.assertEqual(genius.get(OLD_GATEWAY, '/v1/account', 'token', 5), {'ok': True})
        # A component that still holds the old address finds the move already saved by the first one, without asking the mirrors again.
        asked = len(self.net.calls)
        self.assertEqual(lease.gateway_call('GET', OLD_GATEWAY + '/v1/lease', 'token'), (200, {'ok': True}))
        self.assertFalse([u for u in self.net.calls[asked:] if u.endswith('endpoint.json')])

    def test_when_the_server_has_not_moved_the_failure_is_reported_as_before(self):
        self.net.down.add(OLD_GATEWAY); self.publish(1, gateway=OLD_GATEWAY)   # the file says the same address
        with self.assertRaises(genius.GatewayError) as caught: genius.post(OLD_GATEWAY, '/v1/translate', {}, 'token', 5)
        self.assertEqual((caught.exception.status, caught.exception.code), (0, 'UNREACHABLE'))
        self.assertIsNone(lease.gateway_call('POST', OLD_GATEWAY + '/v1/lease', 'token', {}))

    def test_a_refusal_from_a_working_server_does_not_look_for_another(self):
        def answer(request, timeout=None): raise urllib.error.HTTPError(request.full_url, 403, 'no', {}, io.BytesIO(b'{"error":"LICENSE_REVOKED"}'))
        self.publish(1, gateway=NEW_GATEWAY)
        with patch('urllib.request.urlopen', answer), self.assertRaises(genius.GatewayError) as caught: genius.post(OLD_GATEWAY, '/v1/lease', {}, 't', 5)
        self.assertEqual((caught.exception.status, caught.exception.code), (403, 'LICENSE_REVOKED'))
        self.assertIsNone(endpoint.current())   # the file was not even read

    def test_a_down_tunnel_counts_as_a_failure(self):
        for status in (502, 503, 504, 520, 523, 530):
            endpoint._state['failure_at'] = -endpoint.FAILURE_GAP; endpoint.folder().joinpath('directory.json').unlink(missing_ok=True); endpoint._state['memo'] = None
            self.publish(status, gateway=NEW_GATEWAY)
            def answer(request, timeout=None, status=status):
                if request.full_url.startswith(OLD_GATEWAY): raise urllib.error.HTTPError(request.full_url, status, 'down', {}, io.BytesIO(b''))
                return self.net(request, timeout)
            with patch('urllib.request.urlopen', answer): self.assertEqual(genius.post(OLD_GATEWAY, '/v1/x', {}, 't', 5), {'ok': True}, status)

    def test_it_asks_at_most_once_every_ten_minutes(self):
        self.net.down.add(OLD_GATEWAY)   # no file anywhere: nothing can be learnt
        self.assertIsNone(endpoint.failover(OLD_GATEWAY, now=1000.0)); asked = len(self.net.calls)
        self.assertGreater(asked, 0)
        self.assertIsNone(endpoint.failover(OLD_GATEWAY, now=1000.0 + endpoint.FAILURE_GAP - 1)); self.assertEqual(len(self.net.calls), asked)
        self.publish(1, gateway=NEW_GATEWAY)
        self.assertEqual(endpoint.failover(OLD_GATEWAY, now=1000.0 + endpoint.FAILURE_GAP), NEW_GATEWAY)

    def test_the_portal_address_is_followed_too(self):
        self.publish(1, gateway=OLD_GATEWAY, billing_url=NEW_BILLING)
        self.assertEqual(endpoint.failover(OLD_BILLING, 'billing_url'), NEW_BILLING)
        self.assertEqual(billing.remembered(), {})
        billing.remember('CODE-1', OLD_BILLING)
        self.assertEqual(billing.remembered()['portal_url'], NEW_BILLING)   # the remembered Customer Code page follows the move

    def test_helpers(self):
        self.assertTrue(endpoint.same_origin('https://a.example/x', 'https://a.example/y')); self.assertFalse(endpoint.same_origin('https://a.example', 'https://b.example'))
        self.assertEqual(endpoint.swap_origin('https://a.example/v1/lease?x=1', 'https://b.example'), 'https://b.example/v1/lease?x=1')


class LeaseFreshTests(unittest.TestCase):
    def test_a_fresh_licence_asks_for_a_lease_even_when_the_one_on_the_machine_is_not_due(self):
        asked = []
        def command(payload):
            asked.append(payload['action'])
            return {'lease_status': {'http_status': 200, 'lease': 'VALID', 'renew': False}, 'credential': {'status': 'INVALID'}}.get(payload['action'], {})
        with patch.object(lease, 'license_command', command):
            self.assertEqual(lease._renew(), {'lease': 'VALID', 'renewed': False}); self.assertEqual(asked, ['lease_status'])   # not due: nothing more
            asked.clear(); result = lease._renew(fresh=True)
        self.assertEqual(asked, ['lease_status', 'credential', 'machine_pubkey'])   # fresh: it goes on to ask the gateway
        self.assertEqual(result['renewed'], False)


class PublishScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        key = Ed25519PrivateKey.generate(); self.key = key
        pem = Path(self.temp.name) / 'key.pem'
        pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        patcher = patch.dict(os.environ, {'ENDPOINT_SIGNING_KEY': str(pem)}); patcher.start(); self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('publish_endpoint', Path(__file__).resolve().parents[2] / 'packaging' / 'publish_endpoint.py')
        self.script = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.script)

    def test_what_it_writes_is_what_the_app_accepts(self):
        raw, signature = self.script.make('https://gateway.example/', 'https://billing.example', 1700000000)
        out = Path(self.temp.name) / 'pages'; out.mkdir()
        self.script.write(out, raw, signature)
        data = endpoint.verify((out / 'endpoint.json').read_bytes(), (out / 'endpoint.json.sig').read_text(encoding='ascii').strip(), keys=[public_of(self.key)])
        self.assertEqual((data['serial'], data['gateway'], data['billing']), (1700000000, 'https://gateway.example', 'https://billing.example'))

    def test_an_address_the_app_would_refuse_is_never_published(self):
        for gateway in ('http://gateway.example', 'https://gateway.example/path', 'gateway.example'):
            with self.assertRaises(endpoint.EndpointError, msg=gateway): self.script.make(gateway, 'https://billing.example')

    def test_the_serial_must_go_up(self):
        out = Path(self.temp.name) / 'pages'; out.mkdir()
        self.script.write(out, *self.script.make('https://a.example', 'https://b.example', 100))
        with self.assertRaises(SystemExit): self.script.write(out, *self.script.make('https://c.example', 'https://d.example', 100))
        self.script.write(out, *self.script.make('https://c.example', 'https://d.example', 101))


if __name__ == '__main__':
    unittest.main()
