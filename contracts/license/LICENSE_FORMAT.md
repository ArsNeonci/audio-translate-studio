# Licence and lease formats

The wire formats shared by the issuer (Python: `admin-system-server/shared-license-sdk/license_sdk/crypto.py`, used by the admin and the gateway) and the verifier on the customer's machine (Rust: `security-core/src/license.rs`, `lease.rs`). Neither side may change a format alone. Fixed test vectors: `vectors.json`, made by `make_vectors.py`.

| Check | Command |
|---|---|
| Python SDK reproduces the vectors byte for byte | `.venv\Scripts\python.exe contracts\license\make_vectors.py --check` |
| Rust verifies every vector, expected error included | `cargo test contract_vectors` in `security-core` |

## Encoding
- **base64url** without padding for keys, signatures and whole tokens.
- **Canonical JSON** is what gets signed: keys sorted, separators `,` and `:` with no spaces, every non-ASCII character written as `\uXXXX` (characters outside the BMP become a UTF-16 surrogate pair), no NaN or Infinity. Python: `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)`. Rust: `license::canonical`.
- **Signature** = Ed25519 over `domain` + one zero byte + canonical JSON of the value. Rust verifies with `verify_strict`.
- Decoding refuses duplicate fields, and Rust also refuses unknown fields (`deny_unknown_fields`).

## Signing domains
Each domain is used for exactly one purpose, so a key or signature made for one cannot pass as another:

| Domain | Signs | Signed by |
|---|---|---|
| `product-signing-key-v1` | the certificate of a licence signer | the product root key (admin) |
| `machine-license-v1` | a licence payload | the licence signer (admin) |
| `product-lease-key-v1` | the certificate of a lease signer | the product root key (admin) |
| `machine-lease-v1` | a lease payload | the lease signer (gateway) |

The root public key is compiled into `security-core` from `trust-anchor.<edition>.json`.

## Licence token
base64url(canonical JSON) of:
```
{"scheme": "ed25519-v1",
 "certificate": {"payload": {"product_id", "key_version", "public_key"}, "signature": <product-signing-key-v1 by root>},
 "payload": {"license_id", "entitlement_id", "customer_id", "product_id", "machine_id", "sequence",
             "activated_at", "issued_at", "expires_at", "key_version"},
 "signature": <machine-license-v1 by certificate.public_key>}
```
The verifier refuses (error code in brackets):
- the token is longer than 32 768 characters, is not base64url or JSON, has unknown or duplicate fields, or the scheme is not `ed25519-v1` [INVALID];
- either signature fails [INVALID];
- the certificate or payload names another product [WRONG_PRODUCT];
- `sequence` is 0, `key_version` is 0 or differs from the certificate's [INVALID];
- an id is empty, longer than 80, or has a character other than ASCII letters, digits, `_` and `-` [INVALID];
- `machine_id` is not 64 lowercase hex [INVALID];
- the times are not RFC 3339, or the order `activated_at <= issued_at < expires_at` does not hold [INVALID];
- `machine_id` is another machine [WRONG_MACHINE].

When the licence is used, `expires_at` gives EXPIRED and a clock earlier than the last verified time by more than 300 s gives CLOCK_ROLLBACK. A renewal must keep `license_id`, `entitlement_id`, `customer_id` and `activated_at`, raise `sequence` by exactly 1 and extend `expires_at`.

## Lease token
```
{"scheme": "ed25519-lease-v1",
 "certificate": {"payload": {"product_id", "key_version", "public_key"}, "signature": <product-lease-key-v1 by root>},
 "payload": {"license_id", "machine_id", "product_id", "counter", "nonce", "issued_at", "expires_at", "key_version",
             "wrapped_key": {"eph", "nonce", "ct"}, "grace_seconds"?},
 "signature": <machine-lease-v1 by certificate.public_key>}
```
- At most 8 192 characters. Any decoding, scheme, signature, counter 0 or key-version problem is SECURE_STATE_INVALID; another product is WRONG_PRODUCT; another machine is WRONG_MACHINE.
- `grace_seconds` is optional. When it is absent it is not part of the signed bytes, so older leases verify unchanged. The client uses 3 days when absent and clamps the value to 0–30 days.
- A lease with a lower `counter` than the highest one installed is a rollback.

## Wrapped content key (ECIES)
The 32-byte content key is sealed for one machine: an ephemeral X25519 key with the machine's public key → HKDF-SHA256 (no salt, info `audio-content-key-v1`) → AES-256-GCM key, 12-byte nonce, associated data `audio-content-key-v1`. `wrapped_key` = `{eph, nonce, ct}` in base64url. The machine's X25519 secret is kept DPAPI-sealed by `security-core` (`machine.x25519.dpapi`). The vector holds a fixed test secret; the Rust test seals it the same way and unwraps through the real code path.
