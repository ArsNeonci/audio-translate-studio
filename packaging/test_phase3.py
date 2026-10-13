"""Phase 3 unit tests that need no native build: the release secret scanner."""
from pathlib import Path
import tempfile
import unittest

from scan_secrets import scan


class SecretScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'app').mkdir()

    def write(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return path

    def test_clean_tree_passes(self):
        self.write('app/ok.py', 'print("hello")\n')
        self.write('app/public-config.json', '{"product_id":"audio-translate","root_public_key":"AAAA"}')
        self.write('deploy/gateway.env.example', 'ADMIN_TOKEN=\nGEMINI_API_KEY=\n')
        self.assertEqual(scan(self.root), [])

    def test_catches_pem_token_and_blobs(self):
        self.write('app/leak.txt', '-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n')
        self.write('app/conf.env', 'ADMIN_TOKEN=abcdef0123456789abcdef\n')
        self.write('app/state.dpapi', b'\x00\x01\x02binary')
        self.write('app/db.sqlite3', b'SQLite format 3\x00')
        self.write('app/raw.json', '{"content_key":"' + 'a' * 64 + '"}')
        reasons = {reason for _, reason in scan(self.root)}
        self.assertEqual(reasons, {'pem-private-key', 'assigned-api-token', 'forbidden file: state.dpapi',
                                   'forbidden file: db.sqlite3', 'named-raw-private-key'})

    def test_skips_third_party_and_models(self):
        self.write('node_modules/x/state.dpapi', b'junk')
        self.write('models/weights.dpapi', b'junk')
        self.assertEqual(scan(self.root), [])


if __name__ == '__main__':
    unittest.main()
