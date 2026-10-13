"""Write contracts/license/vectors.json: fixed test vectors for the licence and lease formats (LICENSE_FORMAT.md).

    .venv\\Scripts\\python.exe contracts\\license\\make_vectors.py           rewrite the file
    .venv\\Scripts\\python.exe contracts\\license\\make_vectors.py --check   fail if the file differs from a fresh run

Uses the Python SDK (../admin-system-server/shared-license-sdk), the code that issues licences and leases. Every key is a
fixed test key that signs nothing real. Ed25519 signatures are deterministic, so a fresh run must give the same bytes;
--check is the Python side of the contract. The Rust side reads the same file in security-core/src/tests.rs.
The ECIES wrap uses a random ephemeral key and nonce, so it is written once and only checked by unwrapping.
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT.parent / 'admin-system-server' / 'shared-license-sdk'))
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey  # noqa: E402
from license_sdk.crypto import b64, canonical, decode, lease_token, private, public, sign, token, unwrap_content_key, wrap_content_key  # noqa: E402

OUT = HERE / 'vectors.json'
PRODUCT = json.loads((ROOT / 'security-core' / 'trust-anchor.json').read_text(encoding='utf-8'))['product_id']
ROOT_KEY, LICENSE_SIGNER, LEASE_SIGNER = private(bytes([101]) * 32), private(bytes([102]) * 32), private(bytes([103]) * 32)
MACHINE, OTHER_MACHINE = 'a1' * 32, 'b2' * 32
MACHINE_X25519 = X25519PrivateKey.from_private_bytes(bytes([104]) * 32)
CONTENT_KEY = bytes(range(32))


def certificate(signer, domain, key_version=1, product=PRODUCT):
    cert = {'product_id': product, 'key_version': key_version, 'public_key': public(signer)}
    return {'payload': cert, 'signature': sign(ROOT_KEY, domain, cert)}


def license_payload(**changes):
    payload = {'license_id': 'lic-test-1', 'entitlement_id': 'ent-test-1', 'customer_id': 'cust-test-1', 'product_id': PRODUCT,
               'machine_id': MACHINE, 'sequence': 1, 'activated_at': '2026-01-01T00:00:00+00:00', 'issued_at': '2026-01-02T00:00:00+00:00',
               'expires_at': '2026-02-01T00:00:00+00:00', 'key_version': 1}
    payload.update(changes)
    return payload


def lease_payload(wrapped, **changes):
    payload = {'license_id': 'lic-test-1', 'machine_id': MACHINE, 'product_id': PRODUCT, 'counter': 1, 'nonce': '0011223344556677',
               'issued_at': '2026-01-02T00:00:00+00:00', 'expires_at': '2026-01-09T00:00:00+00:00', 'key_version': 1, 'wrapped_key': wrapped}
    payload.update(changes)
    return payload


def envelope(scheme, cert, payload, signature):
    return b64(canonical({'scheme': scheme, 'certificate': cert, 'payload': payload, 'signature': signature}))


def edited(token_text, change):
    """Re-encode a token after changing its decoded envelope (signatures stay as they were)."""
    value = decode(token_text); change(value); return b64(canonical(value))


def build(wrapped):
    lic_cert, lease_cert = certificate(LICENSE_SIGNER, 'product-signing-key-v1'), certificate(LEASE_SIGNER, 'product-lease-key-v1')
    valid = token(lic_cert, license_payload(), LICENSE_SIGNER)
    licenses = [
        {'name': 'valid', 'token': valid, 'machine': MACHINE, 'expect': 'OK'},
        {'name': 'valid renewal, sequence 2, key version 2', 'machine': MACHINE, 'expect': 'OK',
         'token': token(certificate(private(bytes([105]) * 32), 'product-signing-key-v1', 2), license_payload(sequence=2, key_version=2, expires_at='2026-03-01T00:00:00+00:00'), private(bytes([105]) * 32))},
        {'name': 'non-ASCII ids are refused by the id rule', 'machine': MACHINE, 'expect': 'INVALID', 'token': token(lic_cert, license_payload(customer_id='khách-1'), LICENSE_SIGNER)},
        {'name': 'other machine', 'token': valid, 'machine': OTHER_MACHINE, 'expect': 'WRONG_MACHINE'},
        {'name': 'other product', 'machine': MACHINE, 'expect': 'WRONG_PRODUCT',
         'token': token(certificate(LICENSE_SIGNER, 'product-signing-key-v1', product='another-product'), license_payload(product_id='another-product'), LICENSE_SIGNER)},
        {'name': 'payload edited after signing', 'machine': MACHINE, 'expect': 'INVALID', 'token': edited(valid, lambda e: e['payload'].update(expires_at='2099-01-01T00:00:00+00:00'))},
        {'name': 'certificate signed for leases, not licences', 'machine': MACHINE, 'expect': 'INVALID', 'token': token(certificate(LICENSE_SIGNER, 'product-lease-key-v1'), license_payload(), LICENSE_SIGNER)},
        {'name': 'payload signed with the lease domain', 'machine': MACHINE, 'expect': 'INVALID',
         'token': envelope('ed25519-v1', lic_cert, license_payload(), sign(LICENSE_SIGNER, 'machine-lease-v1', license_payload()))},
        {'name': 'unknown payload field', 'machine': MACHINE, 'expect': 'INVALID', 'token': token(lic_cert, license_payload(extra='x'), LICENSE_SIGNER)},
        {'name': 'wrong scheme', 'machine': MACHINE, 'expect': 'INVALID', 'token': edited(valid, lambda e: e.update(scheme='ed25519-v2'))},
        {'name': 'sequence 0', 'machine': MACHINE, 'expect': 'INVALID', 'token': token(lic_cert, license_payload(sequence=0), LICENSE_SIGNER)},
        {'name': 'key version differs from the certificate', 'machine': MACHINE, 'expect': 'INVALID', 'token': token(lic_cert, license_payload(key_version=2), LICENSE_SIGNER)},
        {'name': 'machine id not 64 hex', 'machine': 'A1' * 32, 'expect': 'INVALID', 'token': token(lic_cert, license_payload(machine_id='A1' * 32), LICENSE_SIGNER)},
        {'name': 'expires before it is issued', 'machine': MACHINE, 'expect': 'INVALID', 'token': token(lic_cert, license_payload(expires_at='2026-01-01T12:00:00+00:00'), LICENSE_SIGNER)},
        {'name': 'not base64url', 'machine': MACHINE, 'expect': 'INVALID', 'token': 'not a token!'},
    ]
    valid_lease = lease_token(lease_cert, lease_payload(wrapped), LEASE_SIGNER)
    leases = [
        {'name': 'valid', 'token': valid_lease, 'machine': MACHINE, 'expect': 'OK'},
        {'name': 'valid with a server grace', 'machine': MACHINE, 'expect': 'OK', 'token': lease_token(lease_cert, lease_payload(wrapped, grace_seconds=86400), LEASE_SIGNER)},
        {'name': 'other machine', 'token': valid_lease, 'machine': OTHER_MACHINE, 'expect': 'WRONG_MACHINE'},
        {'name': 'licence certificate cannot sign a lease', 'machine': MACHINE, 'expect': 'SECURE_STATE_INVALID', 'token': lease_token(lic_cert, lease_payload(wrapped), LICENSE_SIGNER)},
        {'name': 'lease certificate cannot sign a licence (checked as a licence)', 'machine': MACHINE, 'expect': 'INVALID', 'as': 'license',
         'token': token(lease_cert, license_payload(), LEASE_SIGNER)},
        {'name': 'payload edited after signing', 'machine': MACHINE, 'expect': 'SECURE_STATE_INVALID', 'token': edited(valid_lease, lambda e: e['payload'].update(counter=99))},
        {'name': 'counter 0', 'machine': MACHINE, 'expect': 'SECURE_STATE_INVALID', 'token': lease_token(lease_cert, lease_payload(wrapped, counter=0), LEASE_SIGNER)},
        {'name': 'unknown field in the wrapped key', 'machine': MACHINE, 'expect': 'SECURE_STATE_INVALID', 'token': lease_token(lease_cert, lease_payload({**wrapped, 'x': 'y'}), LEASE_SIGNER)},
        {'name': 'licence scheme name', 'machine': MACHINE, 'expect': 'SECURE_STATE_INVALID', 'token': edited(valid_lease, lambda e: e.update(scheme='ed25519-v1'))},
    ]
    signatures = [{'domain': domain, 'value': value, 'public_key': public(ROOT_KEY), 'signature': sign(ROOT_KEY, domain, value)}
                  for domain, value in (('product-signing-key-v1', {'b': 1, 'a': 'x'}), ('machine-license-v1', {'name': 'Nguyễn 王', 'n': [1, 2]}))]
    canonicals = [{'value': value, 'canonical': canonical(value).decode('ascii')} for value in
                  ({'b': 1, 'a': [True, None, 0.5]}, {'text': 'Việt 王 😀'}, {'nested': {'z': {}, 'a': []}})]
    return {
        'about': 'Fixed test vectors for contracts/license/LICENSE_FORMAT.md. Test keys only. Regenerate with make_vectors.py.',
        'product_id': PRODUCT,
        'root_public_key': public(ROOT_KEY),
        'canonical': canonicals,
        'signatures': signatures,
        'licenses': licenses,
        'leases': leases,
        'content_key': {'machine_x25519_private': b64(bytes([104]) * 32), 'machine_x25519_public': b64(MACHINE_X25519.public_key().public_bytes_raw()),
                        'wrapped': wrapped, 'key': b64(CONTENT_KEY)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    previous = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else None
    wrapped = previous['content_key']['wrapped'] if previous else wrap_content_key(b64(MACHINE_X25519.public_key().public_bytes_raw()), CONTENT_KEY)
    if unwrap_content_key(MACHINE_X25519, wrapped) != CONTENT_KEY: raise SystemExit('the stored wrapped key does not unwrap to the content key')
    fresh = build(wrapped)
    text = json.dumps(fresh, ensure_ascii=False, indent=1) + '\n'
    if args.check:
        if previous != fresh: raise SystemExit('vectors.json differs from what the SDK produces now')
        print(f'Python SDK: vectors.json reproduced exactly ({len(fresh["licenses"])} licence, {len(fresh["leases"])} lease, '
              f'{len(fresh["signatures"])} signature, {len(fresh["canonical"])} canonical vectors); content key unwraps.')
        return
    OUT.write_text(text, encoding='utf-8')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
