"""The licence answer the page reads (api/license.py): a perpetual licence, the lease phase, and the clear message when only the lease lapsed offline."""
import json
import unittest
from unittest.mock import patch

from audio_translate.api import license as lease


def core(answers):
    """A fake security core: answers by action, recording what was asked."""
    asked = []
    def command(payload):
        asked.append(payload['action']); return answers[payload['action']]
    return command, asked


class LicenseLeaseTests(unittest.TestCase):
    def test_perpetual_is_an_expiry_from_2100_on(self):
        for value, expected in (('2126-10-14T00:00:00+00:00', True), ('2100-01-01T00:00:00Z', True), ('2099-12-31T23:59:59Z', False),
                                ('2026-11-01T00:00:00+00:00', False), ('', False), (None, False), ('soon', False)):
            self.assertEqual(lease.perpetual(value), expected, value)

    def test_status_carries_the_lease_phase_and_perpetual(self):
        command, _ = core({'lease_status': {'http_status': 200, 'lease': 'EXPIRED', 'renew': True}})
        with patch.object(lease, 'license_command', command):
            value = lease.describe({'http_status': 200, 'status': 'ACTIVE', 'expires_at': '2126-10-14T00:00:00+00:00'})
        self.assertEqual((value['lease'], value['perpetual']), ('EXPIRED', True))
        self.assertEqual(lease.describe({'status': 'UNACTIVATED'}), {'status': 'UNACTIVATED'})   # nothing to add without a licence

    def denial(self, check, status):
        command, _ = core({'check': check, 'status': status})
        with patch.object(lease, 'license_command', command), patch.object(lease, 'ensure_lease', lambda force=False: {}):
            response = lease.license_denial()
        return json.loads(response.body) if response else None

    def test_a_lapsed_lease_with_a_valid_licence_asks_to_go_online(self):
        refused = {'http_status': 403, 'status': 'LICENSE_EXPIRED', 'error': 'LICENSE_EXPIRED'}
        self.assertEqual(self.denial(refused, {'status': 'ACTIVE'})['error'], 'LEASE_OFFLINE')
        self.assertEqual(self.denial({**refused, 'status': 'LEASE_REQUIRED', 'error': 'LEASE_REQUIRED'}, {'status': 'ACTIVE'})['error'], 'LEASE_OFFLINE')

    def test_a_retired_release_is_told_to_update_instead_of_to_go_online(self):
        refused = {'http_status': 403, 'status': 'LEASE_REQUIRED', 'error': 'LEASE_REQUIRED'}
        with patch.dict(lease._state, {'last': {'lease': 'EXPIRED', 'renewed': False, 'error': 'VERSION_RETIRED'}}):
            self.assertEqual(self.denial(refused, {'status': 'ACTIVE'})['error'], 'VERSION_RETIRED')
            command, _ = core({'lease_status': {'http_status': 200, 'lease': 'EXPIRED'}})
            with patch.object(lease, 'license_command', command): self.assertTrue(lease.describe({'status': 'ACTIVE', 'expires_at': '2030-01-01T00:00:00+00:00'})['update_required'])

    def test_an_expired_licence_still_says_expired(self):
        refused = {'http_status': 403, 'status': 'LICENSE_EXPIRED', 'error': 'LICENSE_EXPIRED'}
        self.assertEqual(self.denial(refused, {'status': 'EXPIRED'})['error'], 'LICENSE_EXPIRED')
        self.assertEqual(self.denial({'status': 'LICENSE_REVOKED', 'error': 'LICENSE_REVOKED'}, {'status': 'ACTIVE'})['error'], 'LICENSE_REVOKED')

    def test_allowed_is_no_denial(self):
        self.assertIsNone(self.denial({'status': 'ACTIVE', 'allowed': True}, {'status': 'ACTIVE'}))


if __name__ == '__main__':
    unittest.main()
