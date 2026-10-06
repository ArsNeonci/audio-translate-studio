# Audio Translate — Security Phase 2

Status: **Phase 2A implemented and tested (client side); 2B/2C in progress.** Branch `security-phase-2`
in `audio-translates/` (not pushed). Build machine has no Administrator rights, so service
registration, Program Files installation and the installer smoke are **prepared as scripts/hooks
for an elevated run**, not executed here (see "Deferred, needs Administrator").

Design goal (unchanged from the brief): raise the effort to self-edit an install for unlimited use,
AI still runs locally. This is not uncrackable DRM; residual risks are listed at the end.

## Architecture decision (important)

The scheduler (`lib/server/jobs.ts`) spawns the native core per workflow and tracks the **child
process lifetime and exit code**. Turning the core into a pure resident service would force a risky
rewrite of that scheduler. Instead:

- The **service** (`audio-security-core.exe service` / `serve`) is the authority. It holds license
  state and (later) the lease/content key, performs integrity checks, and answers queries plus
  **launch authorization** over a named pipe.
- The **launcher** is the same binary spawned by Node for `workflow`/`command` (unchanged process
  contract). Before spawning the Python worker it asks the service to authorize; if the service is
  down it fails `SECURITY_SERVICE_UNAVAILABLE` (release builds), so stopping the service blocks new
  processing. Dev builds keep an in-process fallback behind a compile feature.
- Node license/edition queries and `license_gate.py` talk to the pipe directly, falling back to the
  CLI binary when the pipe is absent.

Consequence documented as residual: the launcher exe is still spawned, but the service
integrity-checks the tree and only authorizes when its own checks pass.

## 2A — Service, IPC, manifest, integrity (done)

### Named-pipe service and IPC (`security-core/src/ipc.rs`)
- Windows service via `StartServiceCtrlDispatcherW` + control handler + `SetServiceStatus`, and a
  `serve` console mode for dev/test. Built only on `windows-sys` (no new crates, offline build).
- Pipe `\\.\pipe\AudioTranslate.<product_id>`. DACL (SDDL `D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)`)
  grants SYSTEM/Administrators full and the interactive user read/write; `PIPE_REJECT_REMOTE_CLIENTS`
  refuses remote clients; no TCP port.
- Requests are 4-byte length-framed, capped at 64 KiB, parsed strict; dispatch is the fixed action
  set (`identity`, `machine`, `status`, `check`, `activate`, `renew`, `credential`, `integrity`,
  `authorize`). No arbitrary command runs.
- Dev fallback is the cargo feature `dev_fallback` (default on for dev/test; release builds pass
  `--no-default-features`). No environment variable can re-enable it in a release build.
- Clients: `lib/server/security-core.ts` (`callSecurityCore`, pipe) with spawn fallback in
  `license.ts`; `worker/audio_translate/core/secure_channel.py` (ctypes named-pipe client) used by
  `license_gate.py` with CLI fallback. Pipe name's product id comes from `licensing/public-config.json`
  (a rendezvous label only, never a trust input).

### Signed payload manifest and integrity (`security-core/src/manifest.rs`, `build.rs`)
- Dedicated Ed25519 **manifest key**, separate from the license root. Public half embedded at compile
  time from `trust-anchor.json` `manifest_public_key` (optional; empty ⇒ dev build, integrity
  "unconfigured" and skipped). Private key stays Admin/build side.
- `payload.manifest.json` = `{version, entries:[{path, sha256, type, version, runtime}], signature}`,
  signed over `{version, entries}` with domain `payload-manifest-v1`.
- Install scope hashes all entries; runtime scope hashes only `runtime`-flagged entries (binary,
  config, encrypted payloads) at service start and before each workflow/command. Multi-GB public
  model weights are excluded. Binary mismatch ⇒ `UNTRUSTED_BINARY`, other mismatch ⇒
  `INTEGRITY_FAILURE`; path traversal in entries is rejected.
- Generator: `packaging/build_manifest.py` (reuses `license_sdk.crypto` so the canonical wire format
  matches the Rust verifier). Wired into `build_installer.py` under `AUDIO_MANIFEST_KEY_FILE`.

### Tamper states and i18n
- Codes `TAMPER_DETECTED`, `INTEGRITY_FAILURE`, `SECURITY_SERVICE_UNAVAILABLE`, `SECURE_STATE_INVALID`,
  `UNTRUSTED_BINARY` (plus `LICENSE_REVOKED`/`LICENSE_EXPIRED` for 2C/6b) block new processing and are
  localized in `lib/i18n/ui-text.ts`. User data is never deleted.

## 2B — Protected worker and vault (implemented, with one documented limitation)

### Asset vault (`worker/audio_translate/core/vault.py`, `packaging/build_vault.py`)
- Assets 1–5 data is AES-256-GCM encrypted (per-asset, logical name as AAD) in `worker/vault/*.vault`.
  The **content key** is released by the service action `content_key`, gated behind integrity +
  an offline license check; the key is embedded in the release core (trust anchor `content_key`,
  via `build.rs`) for 2B and will be replaced by a lease-wrapped key in 2C. Dev builds embed no key.
- Data extracted from code into data files (loaded via the vault, plaintext fallback in dev):
  - asset 1: `worker/config/translation-prompts.json` (STRATEGIES, GROUP_PROMPT, temperatures) —
    exact strings preserved so checkpoint fingerprints are unchanged.
  - asset 2: `worker/config/names.json` (compound/surname/given tables, ambiguous set).
  - asset 3: `worker/config/address-profiles.json` (already a config; loader now vault-backed).
  - asset 4: `worker/config/genre-lexicon.json`, `worker/config/source-cleanup.json`.
- Loaders (`translation/hymt_translation.py`, `translation/names.py`, `translation/lexicon.py`,
  `translation/source_cleanup.py`, `moderation/address.py`) read from the vault, falling back to the
  plaintext source only when no vault file exists (dev). A hardened build ships the `.vault` files and
  drops the plaintext sources.

### Compiling asset code (`packaging/build_protected.py`)
- Nuitka (`--module --mingw64`) is **feasible on this toolchain**: it compiled `names.py` to a
  ~400 KB `.pyd` offline with the bundled gcc, and the compiled module imports and runs in-package.
  The hardened installer compiles the asset modules to `.pyd` and drops the `.py`. PyInstaller is not
  relied on for protection.

### Execution context (documented limitation)
The content key is gated by the service (integrity + license), so a direct `python worker.py` on an
**expired/unlicensed** state gets no key and no asset data. Full per-stage execution-context binding
(so that even on a *currently licensed* machine only an authorized workflow run can obtain the key)
is **not wired through the orchestrator/stage subprocess chain**: doing so safely needs to run the
real multi-stage pipeline, which this environment cannot (no heavy workflow, 2 GiB RAM headroom
rule). The token mechanism belongs in the service; threading it from the launcher through the
orchestrator to each stage is deferred and called out as residual. On a licensed machine a direct
worker call can still obtain asset data; the monetization gate is lease expiry (2C).

### Installer
`build_installer.py` builds the vault and (hardened) compiles modules when `AUDIO_CONTENT_KEY_FILE`
is set; the plaintext asset sources are then dropped. Unset stays dev-plaintext.

## 2C — Lease, machine-wrapped content key, rollback, ModelVault, canary (implemented)

Server repos `admin-system`, `billing-gateway`, `shared-license-sdk` each got their own git repo
(secrets/DBs/keys gitignored) and a "Snapshot before security phase 2C" commit. Code + local tests
only; nothing deployed.

### Lease + content-key wrapping (verified cross-language)
- ECIES: X25519 → HKDF-SHA256 → AES-256-GCM. The service holds a machine X25519 keypair
  (`security-core/src/lease.rs`, DPAPI-sealed); `shared-license-sdk/license_sdk/crypto.py` wraps the
  content key for that public key. Python-wraps / Rust-unwraps verified end to end.
- `admin-system/core.py` `issue_lease(license_id, machine_public, duration_days=7)`: signs a lease
  (cert chain + domain `machine-lease-v1`) carrying license_id, machine_id, a per-license monotonic
  counter, nonce, issued/expires (min of license expiry and now+duration), key_version and the
  wrapped key. Content key is a per-product 32-byte key generated at product registration, stored
  DPAPI-encrypted (`content_keys` table); `content_key(product_id)` exports it for the build.
- Client (`lease.rs`): actions `machine_pubkey`, `install_lease`, and `content_key` (now prefers the
  lease, falling back to the 2B embedded key). Lease stored DPAPI (`lease.dpapi`) with the highest
  counter and last-verified time.
- Rollback: an older lease restored offline (counter < stored highest) → `SECURE_STATE_INVALID`;
  a backward clock vs last-verified → `CLOCK_ROLLBACK`.
- Offline grace: `GRACE_SECONDS` (default 3 days) past expiry still serves the key; beyond →
  `LICENSE_EXPIRED` blocks new processing. History/download stay available (unchanged UI policy).
- Gateway (`billing-gateway/gateway.py`): `POST /v1/lease` forwards to the authority via an injected
  `lease_issuer`; a `guard` on `/v1/translate` and `/v1/tts` calls an injected `evaluator`.

### ModelVault (`worker/audio_translate/core/model_vault.py`)
Interface + reference sealer/opener for a future private/fine-tuned model: AES-256-GCM under the
service-released content key. Public upstream weights are never encrypted. Not routed today.

### Canary / local tamper log
`security-core` appends tamper/integrity failures to a local `security-events.log` (no network, no
user content). `worker/config/*.json` (including any decoy value) is manifest-protected, so touching
it raises `INTEGRITY_FAILURE` and is logged locally.

## 6b — Server-side detection and revocation (implemented, local)

- `admin-system/core.py`: `evaluate_request(license_id, machine_id)` judges each work request on the
  **server clock** (never the client's): `OK`, `LICENSE_EXPIRED`, `LICENSE_REVOKED`, `WRONG_MACHINE`
  or `INVALID`, logging an anomaly event each time a denial happens. `revoke`/`restore` flip license
  status; `events` lists the log. `_suspicious` flags a license with ≥5 denials in 60 minutes.
- Events store only ids, machine id, kind, timestamp and a short detail (counter/reason) — never user
  content (test asserts this).
- The gateway `guard` blocks a revoked/expired license's work requests with the matching code; the
  client shows the i18n message and keeps history/download.
- **A crack that never contacts the server is only blocked when its lease expires** (offline grace
  then block); online, abnormal tokens are detected and can be revoked.

### Tests (server)
- `admin-system/test_lease.py` 6/6: lease wraps the content key for the machine (unwrap matches the
  product key), monotonic counter, server-clock expiry (client clock cannot revoke), revoke blocks /
  restore re-enables, repeated denials flag suspicious with no user content, wrong-machine flagged.
- `admin-system` existing suite 28/28 still pass (content-key generation added to registration).
- `billing-gateway/test_lease_gateway.py` 4/4: `/v1/lease` forwarding, bad machine key rejected,
  unavailable without issuer, guard blocks a revoked work request. `test_gateway.py` 13/13 still pass.
  (`test_platform.py` needs numpy for TTS, absent in this environment — unrelated to these changes.)
- Rust cross-language lease test: install → content_key (source=lease) matches K, counter rollback →
  SECURE_STATE_INVALID, expiry beyond grace → LICENSE_EXPIRED.

### Remaining wiring (not deployable here)
The live app → gateway `/v1/lease` → authority call, periodic lease renewal, and the gateway↔admin
link that feeds `lease_issuer`/`evaluator` in production are integration glue that needs both servers
running; the mechanisms they call are implemented and tested. No deploy was performed.

## Tests and verification (what actually ran here)
- Rust unit tests: **12/12** (license + manifest: sign/verify, wrong key, tampered config vs binary,
  path traversal). `cargo build --release` offline, no warnings.
- Python↔Rust cross-language: Python-signed manifest verified by the Rust core — valid ⇒ VERIFIED,
  tampered config ⇒ INTEGRITY_FAILURE, tampered binary ⇒ UNTRUSTED_BINARY.
- `packaging/test_security_phase2.py`: **5/5** — integrity valid/configured; tampered config, binary
  and manifest signature rejected; named-pipe service queries + authorization; **release build blocks
  workflow and command with SECURITY_SERVICE_UNAVAILABLE when the service is down even with
  `license_gate.py` patched** (tamper scenarios 1, 5, 6, 7, 8).
- Named-pipe round-trip from Python verified against a live `serve` process.
- Regression: `tsc --noEmit`, `eslint`, `check:i18n`, `check:theme` clean; **315 worker tests pass**
  (1 skipped); Phase 1 native integration **5/5** including the real moderation workflow through the
  launcher. `test_security_phase1.py` HTTP case not re-run here (needs a Next build).
- Not measured yet: startup/authorization/integrity overhead benchmark (next).

## Deferred, needs Administrator (prepared, not executed)
- Install/remove/start/stop the service: `packaging/manage_service.ps1` (test name
  `AudioTranslateSecTest`, copied binary, removed after). Tamper scenario 7 against a *real* service,
  and scenarios 9/10/11 (two-machine state, rollback, lease expiry — 2C) run elevated by the operator.
- Program Files installation + per-user migration in `installer.cs`/`build_installer.py`, and the
  silent installer smoke, require admin and the full model/runtime payload; the release core must be
  built with `AUDIO_RELEASE_HARDENED=1` (no dev_fallback) and the installer must register the service.
- Product version must be bumped before building the installer.

## Residual risks
- An Administrator can stop the SYSTEM service and run a fake server on the pipe name (responses are
  not yet signed). Mitigation for Phase 3: sign service responses or verify the server process token.
  A non-admin cannot stop a SYSTEM service or pre-empt the pipe while it runs.
- The launcher exe is still spawned per run; integrity is enforced by the service, not self-checked.
- Offline whole-state/VM rollback is only detected once online (2C); documented, not eliminated.
- Model weights and thin wrappers remain extractable by design.

## Phase 3 requirements (prepared hooks only)
Authenticode and final release signing; signed IPC responses / server-process verification;
strong anti-debug and heavy obfuscation; per-customer builds; output watermarking; TPM/attestation
for the lease key. 2A leaves the manifest key, `dev_fallback` toggle, service model and tamper states
in place for these.

## 2C follow-up: automatic lease renewal, configurable grace, hard lock on expiry

Decision (owner): a customer who bought a plan may use the app for the whole plan period; when the
period ends the app locks, **including a cracked copy**. This follow-up wires that end to end.

### What changed
- **Renewal on app open** (`lib/server/lease.ts`): the app asks the gateway `/v1/lease` (License
  header, machine public key) and the service verifies and stores the lease. Triggers: every page load
  (`GET /api/license`, background), right after activate/renew, and before every admission
  (`licenseDenial`). A lease is renewed once half of it has passed, so an app opened now and then never
  lapses. Concurrent callers share one request; a fresh result is reused for 10 minutes, a failure for
  1 minute. Offline: the request fails quietly and the grace period covers it.
- **Grace is configurable and signed**: `grace_seconds` is a field inside the server-signed lease, so
  it cannot be edited on the machine. Admin sets lifetime (1–90 days, default 7) and grace (0–30 days,
  default 3) per gateway (`PUT /admin/lease-settings`); the client cannot ask for more. A lease without
  the field keeps the 3-day default; the core clamps grace to 30 days.
- **Lease never outlives the license**: expiry is the smaller of the license expiry and now + lifetime.
- **Hard lock**: a release build (no `dev_fallback`) has **no embedded-key fallback** and requires a
  live lease for every admission (`LEASE_REQUIRED` when none, `LICENSE_EXPIRED` after lease + grace).
  Deleting or never installing the lease no longer unlocks assets. `check` (online) and the service
  `authorize` both apply the gate. Dev builds without a lease still pass, for development only.
- **Revocation is immediate**: when the gateway answers `LICENSE_REVOKED`, the app calls `lease_revoke`;
  the lease state is flagged and new processing stops at once. Replaying an old lease (same counter)
  cannot lift it; a lease issued after a restore (higher counter) does. History and downloads remain.
- **Gateway issues leases itself** (`billing-gateway/lease_authority.py`): the app can only reach the
  gateway, so Admin pushes the product's lease signer, certificate and content key over the admin
  channel (`PUT /admin/lease-materials/<product>`) and revoke/restore (`PUT /admin/licenses/<id>`).
  Expired-token requests are refused on the server clock and recorded; repeats flag the license, and
  an optional `auto_revoke` rule revokes it. Events hold ids, machine, kind, time and a short detail only.
- **Admin side** (`admin-system/billing.py`, `run.py`): push lease material, set lifetime/grace,
  revoke/restore (recorded in Admin and on the gateway), view events. API only; no UI screens yet.

### Tests
- Rust unit tests 13/13. `test_security_phase2.py` 10/10, adding: grace comes from the signed lease
  (3 days vs 0 days vs missing vs clamped), renew flag, revocation not liftable by an old lease, and a
  release build refusing without a lease. Phase 1 native 5/5. Worker 315 pass. tsc/eslint/i18n/theme clean.
- Gateway `test_lease_gateway.py` 8/8 + `test_gateway.py` 13/13: lease signed and wrapped for the
  machine, server-set lifetime and grace the client cannot override, lease never outlives the license,
  expired token refused and recorded, revoke/restore, repeats flag and optional auto-revoke, no user content.
- Admin `test_lease.py` 8/8, `test_lease_link.py` 3/3 (Admin pushes to the real gateway code in-process;
  the lease verifies against the Admin root and unwraps to the product key), plus existing suites.

### Hardening of the risks above (done 2026-10-07)

| Earlier risk | Fix | Status |
|---|---|---|
| One vault key per product: a key extracted once opens that version forever | **One content key per released app version** (`content_key_versions`, created on first export for a build). A key taken from one build opens no other build. The app sends its version with the lease request and the gateway wraps that release's key. A build can be **retired** (`retire_version`): it stops receiving leases and its users must update. | Fixed |
| The gateway VPS holds the key that signs leases, so its compromise could mint licenses | The gateway now holds a **lease-only signer** with its own certificate domain (`product-lease-key-v1`). The core accepts it for leases only, so it can never sign a license (test: a license signed with the lease key is rejected as INVALID). The license signer and root stay on the Admin machine. | Fixed |
| Signing material readable from a copied database or backup | Material is **AES-256-GCM encrypted at rest** under `LEASE_MASTER_KEY` (32+ characters, in the service environment, not in the database). Without the key the lease service stays off and logs that loudly. | Fixed (see limit below) |
| A cracked copy that patches the service binary itself | Cannot be closed by code alone: the patched binary can skip any check it contains. Needs the signed-binary work of Phase 3 (Authenticode, and clients checking the signature of the process on the pipe). | Open, Phase 3 |

Operating notes
- Release flow: `python export_build_keys.py --product <id> --version <x.y.z> --out <file outside any repo>`,
  point `AUDIO_CONTENT_KEY_FILE` at it, bump the product version, build, then push lease material
  (`/api/billing/lease-materials`). Later, `/api/billing/retire-version` retires an old build.
- Keep an offline copy of `LEASE_MASTER_KEY`. Losing it only means Admin must push the material again.
- Limit that remains: whoever has root on the gateway host can read the master key from the service
  environment and so the material. The fix shrinks what that exposes (a lease signer, not a license
  signer) rather than removing it; file mode 600 and normal host hardening still apply.
- Existing leases signed under the earlier certificate domain no longer verify; none had shipped.
- The lease request carries the app version, so older apps that omit it receive only the legacy key,
  which opens only vaults built with that legacy key.

Tests: Rust 13; `test_security_phase2.py` 11 (adds forged-license rejection); admin `test_lease.py` 11
(lease signer separation, per-version keys and retirement, export refuses a path inside a repository),
`test_lease_link.py` 4; gateway `test_lease_gateway.py` 10 (encrypted at rest, wrong master key fails,
version routing, retired and unsupported builds) plus `test_gateway.py` 13; tsc and eslint clean.

### Residual risks that remain
- A cracked copy that **patches the service binary** is not stopped by the lease alone (Phase 3).
- Per-stage execution context is still not threaded through the orchestrator (2B limitation).
- A key leaked from a build you shipped still opens that one build; retire it to force an update.
- Not run here: the live app against a running gateway (needs both servers), the real service as
  Administrator, two physical machines, and benchmarks.
