"""Phase 2A integration: signed manifest integrity, named-pipe service and fail-closed launch.

Builds synthetic cores (never the live anchor) with a dedicated manifest key, then checks:
integrity verification and tamper detection, the named-pipe service round-trip and launch
authorization, and that a release build (no dev_fallback) blocks all processing when the service
is down even if the Python gate is patched. Admin-only pieces (installing the real Windows
service, Program Files) are covered by packaging/manage_service.ps1 and the installer smoke, run
elevated by the operator; see SECURITY_PHASE_2_RESULT.md.

Run with the Product venv: python -m unittest discover -s packaging -p "test_security_phase2.py".
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest

from build_security_core import build, ROOT
import build_manifest as bm
sys.path.insert(0, str(ROOT.parent / 'shared-license-sdk'))
sys.path.insert(0, str(ROOT / 'worker'))
from license_sdk.crypto import private, public, sign, token, lease_token, wrap_content_key
from audio_translate.core import secure_channel as sc

PRODUCT = 'audio-translate'


def _anchor(base, root_key, manifest_key, content_key):
    import base64
    path = base / 'anchor.json'
    path.write_text(json.dumps({'product_id': PRODUCT, 'root_public_key': public(root_key),
                                'manifest_public_key': public(manifest_key),
                                'content_key': base64.urlsafe_b64encode(content_key).rstrip(b'=').decode()}))
    return path


def _app_tree(base, name):
    app = base / name
    (app / 'security-core' / 'bin').mkdir(parents=True)
    (app / 'worker' / 'config').mkdir(parents=True)
    (app / 'worker' / 'config' / 'genius.json').write_text('{"ok":1}', encoding='utf-8')
    (app / 'licensing').mkdir()
    (app / 'licensing' / 'public-config.json').write_text(json.dumps({'product_id': PRODUCT}), encoding='utf-8')
    return app


class Phase2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'data' / 'verification').mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='security-phase2-', dir=ROOT / 'data' / 'verification')
        cls.base = Path(cls.temp.name)
        cls.root_key = private(secrets.token_bytes(32))
        cls.manifest_key = private(secrets.token_bytes(32))
        cls.content = secrets.token_bytes(32)
        anchor = _anchor(cls.base, cls.root_key, cls.manifest_key, cls.content)

        # Dev build (default features): CLI/in-process fallback available, used for integrity + serve.
        cls.app = _app_tree(cls.base, 'app')
        cls.binary = build(anchor, cls.app / 'security-core' / 'bin' / 'audio-security-core.exe')
        bm.write(cls.app, '1.2.0', cls.manifest_key)

        # Release build (no dev_fallback): must require the running service to authorize.
        cls.app2 = _app_tree(cls.base, 'app2')
        cls.release = build(anchor, cls.app2 / 'security-core' / 'bin' / 'audio-security-core.exe', dev_fallback=False)
        bm.write(cls.app2, '1.2.0', cls.manifest_key)

        cls.machine = cls.cli(cls, {'action': 'machine'})['machine_id']

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cli(self, payload, binary=None, state=None):
        env = {**os.environ, 'AUDIO_LICENSE_STATE_ROOT': str(state or self.base / 'state')}
        result = subprocess.run([str(binary or self.binary)], input=json.dumps(payload), capture_output=True,
                                text=True, encoding='utf-8', env=env, timeout=60)
        try:
            return json.loads(result.stdout)
        except ValueError:
            return {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}

    def issue(self, days=30, sequence=1, key_version=1, machine=None):
        now = datetime.now(timezone.utc)
        signer = private(bytes([18 + key_version]) * 32)
        cert = {'product_id': PRODUCT, 'key_version': key_version, 'public_key': public(signer)}
        certificate = {'payload': cert, 'signature': sign(self.root_key, 'product-signing-key-v1', cert)}
        payload = {'license_id': 'synthetic', 'entitlement_id': 'synthetic-ent', 'customer_id': 'synthetic-cust',
                   'product_id': PRODUCT, 'machine_id': machine or self.machine, 'sequence': sequence,
                   'activated_at': (now - timedelta(days=3)).isoformat(), 'issued_at': (now - timedelta(days=2)).isoformat(),
                   'expires_at': (now + timedelta(days=days)).isoformat(), 'key_version': key_version}
        return token(certificate, payload, signer)

    # --- Integrity ---------------------------------------------------------
    def test_integrity_valid_and_configured(self):
        self.assertEqual(self.cli({'action': 'identity'})['product_id'], PRODUCT)
        for scope in ('install', 'runtime'):
            result = self.cli({'action': 'integrity', 'scope': scope})
            self.assertEqual(result['status'], 'VERIFIED', result)
            self.assertTrue(result['configured'])

    def test_integrity_tampered_config_and_binary(self):
        config = self.app / 'worker' / 'config' / 'genius.json'
        original = config.read_bytes()
        try:
            config.write_text('{"ok":2}', encoding='utf-8')
            # Config is runtime-flagged, so both scopes catch it.
            self.assertEqual(self.cli({'action': 'integrity', 'scope': 'runtime'})['status'], 'INTEGRITY_FAILURE')
            self.assertEqual(self.cli({'action': 'integrity', 'scope': 'install'})['status'], 'INTEGRITY_FAILURE')
        finally:
            config.write_bytes(original)
        self.assertEqual(self.cli({'action': 'integrity', 'scope': 'runtime'})['status'], 'VERIFIED')

    def test_tampered_manifest_signature_rejected(self):
        manifest_path = self.app / 'payload.manifest.json'
        original = manifest_path.read_text(encoding='utf-8')
        try:
            doc = json.loads(original)
            doc['entries'][0]['sha256'] = 'f' * 64  # change a hash without re-signing
            manifest_path.write_text(json.dumps(doc), encoding='utf-8')
            self.assertEqual(self.cli({'action': 'integrity', 'scope': 'runtime'})['status'], 'INTEGRITY_FAILURE')
            doc = json.loads(original)
            doc['signature'] = doc['signature'][:-4] + ('AAAA' if not doc['signature'].endswith('AAAA') else 'BBBB')
            manifest_path.write_text(json.dumps(doc), encoding='utf-8')
            self.assertEqual(self.cli({'action': 'integrity', 'scope': 'runtime'})['status'], 'INTEGRITY_FAILURE')
        finally:
            manifest_path.write_text(original, encoding='utf-8')

    # --- Named-pipe service ------------------------------------------------
    def _serve(self, binary):
        state = self.base / f'serve-{secrets.token_hex(4)}'
        proc = subprocess.Popen([str(binary), 'serve'],
                                env={**os.environ, 'AUDIO_LICENSE_STATE_ROOT': str(state)},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(40):
            if sc.available(PRODUCT):
                break
            time.sleep(0.1)
        return proc, state

    def test_pipe_service_queries_and_authorization(self):
        proc, state = self._serve(self.binary)
        try:
            self.assertTrue(sc.available(PRODUCT))
            self.assertEqual(sc.call({'action': 'identity'}, PRODUCT)['product_id'], PRODUCT)
            self.assertEqual(sc.call({'action': 'status'}, PRODUCT)['status'], 'UNACTIVATED')
            # Unprotected command authorizes without a license; protected does not.
            self.assertEqual(sc.call({'action': 'authorize', 'kind': 'command', 'script': 'manage.py', 'payload_action': 'history'}, PRODUCT)['status'], 'AUTHORIZED')
            self.assertEqual(sc.call({'action': 'authorize', 'kind': 'command', 'script': 'manage.py', 'payload_action': 'create'}, PRODUCT)['status'], 'UNACTIVATED')
            self.assertEqual(sc.call({'action': 'authorize', 'kind': 'workflow'}, PRODUCT)['status'], 'UNACTIVATED')
            # Activate over the pipe, then a workflow authorizes (trusted-time may be offline in CI).
            self.assertEqual(sc.call({'action': 'activate', 'token': self.issue()}, PRODUCT, timeout_ms=15000)['status'], 'ACTIVE')
            decision = sc.call({'action': 'authorize', 'kind': 'workflow'}, PRODUCT, timeout_ms=20000)['status']
            self.assertIn(decision, ('AUTHORIZED', 'TRUSTED_TIME_UNAVAILABLE'), decision)
            self.assertEqual(sc.call({'action': 'nope'}, PRODUCT)['status'], 'INVALID_ACTION')
        finally:
            proc.terminate()
            try: proc.wait(timeout=10)
            except Exception: proc.kill()

    # --- Vault content key (2B) --------------------------------------------
    def test_content_key_gated_and_vault_round_trip(self):
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import build_vault as bv
        state = self.base / 'ck-state'
        # Gated behind the license: no key before activation.
        self.assertEqual(self.cli({'action': 'content_key'}, state=state)['status'], 'UNACTIVATED')
        self.assertEqual(self.cli({'action': 'activate', 'token': self.issue()}, state=state)['status'], 'ACTIVE')
        result = self.cli({'action': 'content_key'}, state=state)
        self.assertEqual(result['status'], 'OK', result)
        key = base64.urlsafe_b64decode(result['content_key'] + '=' * ((-len(result['content_key'])) % 4))
        self.assertEqual(key, self.content)
        # A vault file sealed with that key opens back to the source bytes.
        (self.app / 'worker' / 'config' / 'names.json').write_text(
            json.dumps({'version': 1, 'surnames': {'王': 'Vương'}}), encoding='utf-8')
        bv.build(self.app, self.content, {'names': 'worker/config/names.json'})
        raw = (self.app / 'worker' / 'vault' / 'names.vault').read_bytes()
        self.assertTrue(raw.startswith(b'ATVAULT1\n'))
        opened = AESGCM(key).decrypt(raw[9:21], raw[21:], b'names')
        self.assertEqual(json.loads(opened)['surnames']['王'], 'Vương')

    def test_client_lease_install_unwrap_and_rollback(self):
        import base64
        state = self.base / 'lease-client-state'
        self.assertEqual(self.cli({'action': 'activate', 'token': self.issue()}, state=state)['status'], 'ACTIVE')
        machine_pub = self.cli({'action': 'machine_pubkey'}, state=state)['machine_pubkey']
        signer = private(bytes([19]) * 32)
        cert = {'product_id': PRODUCT, 'key_version': 1, 'public_key': public(signer)}
        certificate = {'payload': cert, 'signature': sign(self.root_key, 'product-signing-key-v1', cert)}
        now = datetime.now(timezone.utc)
        leased_key = secrets.token_bytes(32)

        def lease(counter, days):
            payload = {'license_id': 'synthetic', 'machine_id': self.machine, 'product_id': PRODUCT, 'counter': counter,
                       'nonce': secrets.token_hex(8), 'issued_at': now.isoformat(),
                       'expires_at': (now + timedelta(days=days)).isoformat(), 'key_version': 1,
                       'wrapped_key': wrap_content_key(machine_pub, leased_key)}
            return lease_token(certificate, payload, signer)

        self.assertEqual(self.cli({'action': 'install_lease', 'token': lease(1, 7)}, state=state)['status'], 'OK')
        result = self.cli({'action': 'content_key'}, state=state)
        self.assertEqual(result.get('source'), 'lease', result)
        key = base64.urlsafe_b64decode(result['content_key'] + '=' * ((-len(result['content_key'])) % 4))
        self.assertEqual(key, leased_key)  # lease key overrides the embedded one and unwraps correctly
        self.assertEqual(self.cli({'action': 'install_lease', 'token': lease(2, 7)}, state=state)['status'], 'OK')
        # An older lease restored offline is a rollback.
        self.assertEqual(self.cli({'action': 'install_lease', 'token': lease(1, 7)}, state=state).get('status'), 'SECURE_STATE_INVALID')

    # --- Fail closed when the service is down (release build) ---------------
    def test_release_blocks_without_service_even_if_python_patched(self):
        # No service is running for app2's product state root; the release launcher must refuse.
        gate = self.app2 / 'worker' / 'audio_translate' / 'core'
        gate.mkdir(parents=True, exist_ok=True)
        (self.app2 / 'worker' / 'audio_translate' / '__init__.py').write_text('', encoding='utf-8')
        (gate / '__init__.py').write_text('', encoding='utf-8')
        (gate / 'license_gate.py').write_text('def assert_allowed(internet=True): return True\n', encoding='utf-8')
        state = self.base / 'release-state'
        workflow = self.cli({'action': 'workflow', 'job_dir': str(self.base / 'nonexistent')}, binary=self.release, state=state)
        self.assertEqual(workflow.get('license_status'), 'SECURITY_SERVICE_UNAVAILABLE', workflow)
        command = self.cli({'action': 'command', 'script': 'manage.py', 'payload': {'action': 'create'}}, binary=self.release, state=state)
        self.assertEqual(command.get('license_status'), 'SECURITY_SERVICE_UNAVAILABLE', command)


if __name__ == '__main__':
    (ROOT / 'data' / 'verification').mkdir(parents=True, exist_ok=True)
    unittest.main()
