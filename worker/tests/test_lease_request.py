"""What the app asks the gateway for when it renews the lease: the product's key (the version is information only), and a clear answer
when the owner retired this release."""
import unittest
from unittest.mock import patch

from audio_translate.api import license as lease


def core(answers):
    def command(payload):
        value = answers[payload['action']]
        return value(payload) if callable(value) else value
    return command


class LeaseRequestTests(unittest.TestCase):
    def renew(self, reply, version='3.2.0'):
        sent = []
        def call(method, url, token, body=None, timeout=20): sent.append((method, url, body)); return reply
        answers = {'lease_status': {'http_status': 200, 'lease': 'VALID', 'renew': True}, 'credential': {'status': 'ACTIVE', 'token': 'tok'},
                   'machine_pubkey': {'machine_pubkey': 'K' * 43}, 'install_lease': {'status': 'OK'}}
        with patch.object(lease, 'license_command', core(answers)), patch.object(lease, 'gateway_call', call), \
                patch.object(lease, 'gateway_endpoint', lambda: 'https://gw.example'), patch.object(lease, 'app_version', lambda: version):
            return lease._renew(), sent

    def test_the_request_asks_for_the_product_key_and_only_reports_the_version(self):
        result, sent = self.renew((200, {'lease': 'L'}))
        self.assertEqual(result, {'lease': 'VALID', 'renewed': True})
        self.assertEqual(sent[0][2], {'machine_public': 'K' * 43, 'key_scope': 'product', 'client_version': '3.2.0'})
        self.assertNotIn('app_version', sent[0][2])                  # nothing in the request makes the version pick a key

    def test_no_version_file_still_renews(self):
        result, sent = self.renew((200, {'lease': 'L'}), version=None)
        self.assertTrue(result['renewed']); self.assertEqual(sent[0][2], {'machine_public': 'K' * 43, 'key_scope': 'product'})

    def test_a_retired_release_is_told_to_update_not_that_its_licence_is_bad(self):
        result, _ = self.renew((403, {'error': 'LEASE_VERSION_RETIRED'}))
        self.assertEqual((result['renewed'], result['error']), (False, 'VERSION_RETIRED'))


if __name__ == '__main__':
    unittest.main()
