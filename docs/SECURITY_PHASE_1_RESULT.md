# Audio Translate — Security Phase 1

Date: 2026-10-03. Product version: 1.1.0. Scope: native trust boundary and application admission; no Phase 2/3 hardening.

## Audit and threat model

The desktop product is a .NET Framework installer containing an appended ZIP. It launches a bundled Python launcher, Node/Next.js 16 standalone backend and Python workers, with a localhost browser UI. It is not an Electron/Tauri application. AI models and processing remain local. Assume the owner can inspect/edit Python, JS/config and may hold Administrator rights.

Before Phase 1, `license_gate.py` read the root public key from editable `public-config.json` and used the Python `shared-license-sdk/service.py` as the final authority. Replacing the root or removing the Python check could bypass admission. Installation files were user-writable in LocalAppData. Build-side artifact hashes did not enforce runtime integrity. DPAPI state, MachineGuid/SMBIOS binding, signatures and time checks did not make an editable verifier trustworthy.

## Implemented boundary

`UI -> Next backend -> native Rust core -> license decision -> native worker launcher -> existing Python/model workflow`.

The Windows executable `audio-security-core.exe` verifies Ed25519 root/delegated-key signatures, Product ID, machine binding, activation/expiry timestamps, renewal identity and sequence, and nondecreasing signing-key version. Strict typed token parsing rejects duplicate/unknown fields. Root and Product ID are compiler constants. No runtime root-key parameter, JSON root loader or Python verifier fallback exists.

The native broker validates a fixed command/action list and chooses installation-relative Python/script paths. It authorizes Start, Retry, Reprocess, Resume and Standalone Tools before spawning the worker. Next license operations call the executable directly. The scheduler also launches through the native broker. Python `license_gate.py` is only an adapter to the executable, providing additional checks during processing. `shared-license-sdk/service.py` remains an Admin/reference test implementation and is excluded from Product payloads.

## Trust, identity and state

- Build-only `security-core/trust-anchor.json` contains the existing Product root public key. Admin writes this public compiler input; Rust embeds it. Runtime config contains only product/version/scheme metadata. Delegated key rotation keeps the same root.
- Machine ID is computed natively from the Windows 64-bit MachineGuid registry value and SMBIOS type-1 System UUID via `GetSystemFirmwareTable`, normalized and SHA-256 hashed. No hostname/IP/MAC binding. Integration tests compare it against the previous WMI fingerprint.
- Native DPAPI uses Machine Scope and the existing entropy for upgrade compatibility. Atomic state writes and an exclusive file lock protect updates. State contains current signed license, signer public key, machine ID, highest sequence, last verified time and key version. Old `license_sequence`/floating timestamps are migrated without deleting the license.
- Entry/launch authorization keeps the existing two-source HTTPS Date quorum policy. Offline status/progress checks validate local expiry and persisted time. No client claim replaces a server-issued token.

Machine-scope DPAPI is encryption at rest, not an anti-Administrator boundary; other users on that computer may decrypt a blob they can access. [Microsoft CryptProtectData documentation](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).

## Installation and compatibility

`packaging/paths.py` centralizes installation/application/core paths versus LocalAppData data/license paths, with Program Files/AudioTranslate as the preferred future installation location. Phase 1 retains the per-user installer to avoid disrupting development. Results/history/preferences/logs and encrypted license state persist outside application binaries. Existing releases are preserved; changed Product code uses 1.1.0. The Admin manifest must be re-registered to release that version through its UI.

yt-dlp, FSMN-VAD, Paraformer, ct-punc, translation, replacement moderation and VieNeu model implementations were not rewritten. A Windows SQLite connection leak discovered in retry regression tests was fixed using explicit connection closure.

## Files changed by this work

- `audio-translates/security-core/`: Rust source, Cargo manifest/lock, build script, public compile-time anchor, native unit tests; generated executable under `bin/`.
- `audio-translates/lib/{security-core,license,rules,jobs}.ts`: native calls, protected command broker and scheduler.
- `audio-translates/worker/license_gate.py`: native interface adapter; `manage.py` and `stage_reset.py`: close SQLite restart connections.
- `audio-translates/packaging/{build_security_core,build_installer,paths,launcher,test_security_phase1}.py`: compilation, native payload, paths and integration tests.
- Product config/manifest, package files, Next tracing config, ignores and README; build version advanced to 1.1.0.
- `admin-system/{builds,audit_package,test_licensing}.py` and README: build-only anchor, native package audit and updated expectations.
- `shared-license-sdk/license_sdk/service.py`: marks the Python implementation as Admin/reference-only.

Existing unrelated worktree changes were preserved. No live customer/license records or existing user license state were reset.

## Verification

- ESLint: PASS.
- Next production build (isolated `.next-security-phase1`): PASS.
- Rust release build for Windows x64 GNU using installed MinGW: PASS. Rust toolchain/dependencies were installed inside workspace `.tools`; no global PATH change. Standard MSVC builds remain supported.
- Rust unit tests: 9 PASS (strict parsing, signature/root tamper, Product/machine mismatch, expiry/rollback, state integrity, DPAPI restart, renewal/rotation and admission allowlist).
- Admin unit/integration tests: 19 PASS.
- Worker regression tests: 113 run, PASS, 1 existing integration-dependent skip.
- Native/Next integration tests: 8 PASS. Real unchanged moderation tool runs to completion through the native broker. Copied Python gate changed to unconditional `return True` does not bypass native admission. Built Next HTTP Start/Retry/Reprocess/Resume/Tools/Preflight reject an expired license despite that Python modification. Status/history remain accessible. Renewal, key rotation, replay rejection, legacy state migration, restart, config-root substitution and signed wrong-machine token/state are tested.
- Windows installer 1.1.0: PASS; 594,607,377 bytes, 35,590 payload files. Re-running the build confirms the existing installer matches current source and release hashes without rebuilding. Prior 1.0.x releases remain unchanged.
- Full release EXE payload audit: PASS; scans all files for Admin private keys, issued tokens and customer IDs, rejects private/config/database material, verifies metadata-only config, excludes the Python SDK/build anchor, and checks the native executable's embedded root against Admin's Product root. Audit reads the appended ZIP directly from the EXE because the existing build cleans temporary staging.
- Actual silent installation into an isolated workspace directory and packaged Node/Python/native runtime smoke: PASS, 12 HTTP checks (expired admission/retry denial, allowed history/download, blocked preview, valid renewal, preview recovery and replay rejection). Production state and normal installation paths were not overwritten.

Artifact: `audio-translates/dist/AudioTranslate-1.1.0.exe`.
Installer SHA-256: `806a70b953049e123f3a63b6d431ddfc881fa2a512dcfa1eb4fd18c2824467ec`.
Persistent installer smoke evidence: `audio-translates/data/verification/licensing-smoke/7cd3979595eb4830b9a41eab48c8be70/result.json`.

Physical license-state copy to another Windows machine has not been executed because a second host is unavailable. Signed B-machine token/state rejection is exercised on this host; that is not a substitute for a two-host DPAPI test. Real heavy ASR/translation/TTS inference was not rerun by this audit; existing regression tests cover their workflow/adapters, and the real moderation integration covers native launch/processing/publication.

## Residual risks and Phase 2/3

This is not uncrackable DRM. Editing only runtime config or the Python license adapter no longer changes the native decision used by the unchanged application. An owner can still replace/patch the unsigned native executable, modify Node to bypass the broker, modify other Python code or invoke extracted local model code outside the application. Native decisions control the supported application launch path, not every possible use of user-owned local interpreters/models. Whole-state/VM rollback, fingerprint spoofing and offline revocation also remain outside Phase 1 guarantees.

Windows Service/ACL enforcement, signed payload manifests, Authenticode, protected execution/online lease/revocation, TPM/attestation, model encryption, anti-debugging, obfuscation and compiling all Python are deferred and were not implemented. These require an explicit next phase; local native code alone cannot enforce an absolute subscription against a machine owner with Administrator access.
