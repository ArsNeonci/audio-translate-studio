"""audio_translate/api/billing.py: the scenarios of scripts/check-billing-portal.cjs (which checked the TypeScript module it
replaces), with the licence service and the gateway scripted."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from audio_translate.api import billing, license as lease


class Scripted:
    def __init__(self):
        self.credential = {'status': 'ACTIVE', 'token': 'LIC.TOKEN'}
        self.sequence, self.installed, self.calls, self.routes, self.lease_renewals = 4, [], [], {}, 0
        self.home = 'https://billing.test'

    def license(self, payload):
        action = payload['action']
        if action == 'credential': return {'http_status': 200 if self.credential['status'] == 'ACTIVE' else 403, **self.credential}
        if action == 'status': return {'http_status': 200, 'status': 'ACTIVE', 'sequence': self.sequence}
        if action == 'renew':
            if payload['token'].startswith('BAD'): return {'http_status': 400, 'status': 'INVALID'}
            self.installed.append(payload['token']); self.sequence += 1
            return {'http_status': 200, 'status': 'ACTIVE', 'sequence': self.sequence}
        return {'http_status': 404, 'status': 'INVALID'}

    def gateway_call(self, method, url, token, body=None, timeout=20):
        self.calls.append({'method': method, 'url': url, 'token': token, 'body': body})
        route = self.routes.get(f'{method} {urlsplit(url).path}')
        return None if route is None else route   # None: offline


class BillingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.s = s = Scripted()
        def lease_now(force=False): s.lease_renewals += 1
        self.patches = [patch.object(billing, 'FILE', Path(temp.name) / 'settings' / 'billing.json'), patch.object(billing, 'license_command', s.license),
                        patch.object(lease, 'gateway_call', s.gateway_call), patch.object(lease, 'gateway_endpoint', lambda: 'https://api.test'),
                        patch.object(lease, 'billing_url', lambda: s.home), patch.object(lease, 'ensure_lease_in_background', lease_now),
                        patch.dict(billing._state, {'fast_until': 0.0, 'at': 0.0, 'checked_code': 0.0})]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def saved(self): return json.loads(billing.FILE.read_text(encoding='utf-8'))
    def reset(self): self.s.calls.clear(); self.s.installed.clear(); self.s.routes = {}

    def test_open_billing(self):
        s = self.s
        # A valid licence: a one-time link; the licence token only goes to the gateway, and the Customer Code is remembered.
        s.routes = {'POST /v1/billing/session': (200, {'url': 'https://billing.test/s/abc?next=license', 'customer_code': 'ABCDE-FGHJK', 'expires_in': 1800})}
        self.assertEqual(billing.open_billing('license'), {'url': 'https://billing.test/s/abc?next=license', 'mode': 'app'})
        self.assertEqual((s.calls[0]['token'], s.calls[0]['body']), ('LIC.TOKEN', {'next': 'license'}))
        self.assertEqual((self.saved()['code'], self.saved()['portal_url']), ('ABCDE-FGHJK', 'https://billing.test'))
        # An expired licence: the remembered code opens the portal with the code filled in; nothing is sent.
        self.reset(); s.credential = {'status': 'EXPIRED'}
        self.assertEqual(billing.open_billing('debt'), {'url': 'https://billing.test/?code=ABCDE-FGHJK', 'mode': 'code'})
        self.assertEqual(s.calls, [])
        # A revoked licence is reported, not hidden behind the fallback.
        self.reset(); s.credential = {'status': 'ACTIVE', 'token': 'LIC.TOKEN'}
        s.routes = {'POST /v1/billing/session': (403, {'error': 'LICENSE_REVOKED'})}
        with self.assertRaisesRegex(billing.BillingError, 'LICENSE_REVOKED'): billing.open_billing('license')
        # Offline with a valid licence: the remembered code; nothing remembered: a clear error.
        self.reset()
        self.assertEqual(billing.open_billing('license')['mode'], 'code')
        billing.FILE.unlink()
        with self.assertRaisesRegex(billing.BillingError, 'GATEWAY_UNREACHABLE'): billing.open_billing('license')
        # No active licence and no remembered code: the portal's start page asks for the Customer Code.
        self.reset(); s.credential = {'status': 'EXPIRED'}
        self.assertEqual(billing.open_billing('license'), {'url': 'https://billing.test/', 'mode': 'home'})
        self.assertEqual(s.calls, [])
        s.credential = {'status': 'UNACTIVATED'}
        self.assertEqual(billing.open_billing('debt'), {'url': 'https://billing.test/', 'mode': 'home'})
        s.home = None
        with self.assertRaisesRegex(billing.BillingError, 'BILLING_CODE_UNKNOWN'): billing.open_billing('license')

    def test_renewals(self):
        s = self.s
        # Installed in order, from the sequence the core already has; a fresh licence gets its lease at once.
        s.routes = {'GET /v1/license/renewals': (200, {'renewals': [{'sequence': 6, 'token': 'T6'}, {'sequence': 5, 'token': 'T5'}]})}
        self.assertEqual(billing.fetch_renewals(True), 2)
        self.assertEqual(s.installed, ['T5', 'T6'])
        self.assertTrue(s.calls[0]['url'].endswith('after=4'))
        self.assertEqual(s.lease_renewals, 1)
        # A bad token stops the chain.
        self.reset(); s.sequence = 6
        s.routes = {'GET /v1/license/renewals': (200, {'renewals': [{'sequence': 7, 'token': 'BAD7'}, {'sequence': 8, 'token': 'T8'}]})}
        self.assertEqual(billing.fetch_renewals(True), 0)
        self.assertEqual(s.installed, [])
        # Throttled: right after a check, a call does not reach the gateway.
        self.reset(); s.routes = {'GET /v1/license/renewals': (200, {'renewals': []})}
        self.assertEqual(billing.fetch_renewals(), 0)
        self.assertEqual(s.calls, [])
        # An expired licence collects nothing in the background.
        self.reset(); s.credential = {'status': 'EXPIRED'}
        self.assertEqual(billing.fetch_renewals(True), 0)
        self.assertEqual(s.calls, [])

    def test_the_customer_code_is_read_once_and_cached(self):
        self.s.routes = {'GET /v1/billing/code': (200, {'code': 'QQQQQ-WWWWW', 'portal_url': 'https://billing.test'})}
        expected = {'code': 'QQQQQ-WWWWW', 'portal_url': 'https://billing.test', 'enabled': True}
        self.assertEqual(billing.billing_info(), expected)
        self.assertEqual(billing.billing_info(), expected)
        self.assertEqual(len(self.s.calls), 1)

    def test_error_codes_for_the_page(self):
        self.assertEqual(billing.error_code(billing.BillingError('LICENSE_REVOKED')), 'LICENSE_REVOKED')
        self.assertEqual(billing.error_code(ValueError('Expecting value: line 1')), 'BILLING_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
