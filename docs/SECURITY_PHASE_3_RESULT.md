# Audio Translate — Security Phase 3

Status: in progress on branch `security-phase-2`. Phase 3 hardens the Phase 2 base. Several items
depend on things this environment cannot provide (a real Authenticode code-signing certificate, a
TPM, and running the full AI pipeline), so they are built as hooks/interfaces and clearly marked
"needs publisher cert / hardware / pipeline". Nothing here is deployed.

## Implemented and tested here

### Peer verification on the IPC pipe (closes the top Phase 2 residual)
`security-core/src/ipc.rs`: before a client trusts the pipe server, release builds confirm the
server process runs as **LocalSystem** (`GetNamedPipeServerProcessId` → open process token →
compare to the well-known SYSTEM SID). A look-alike server a non-admin starts on the same pipe name
runs as the user, not SYSTEM, so the launcher refuses it (`SECURITY_SERVICE_UNAVAILABLE`). Dev
builds (feature `dev_fallback`) skip the check so the console `serve` works.
- Test `packaging/test_security_phase2.py::test_release_rejects_non_system_server_on_the_pipe`:
  a non-SYSTEM `serve` is up and reachable, yet the release launcher refuses to authorize.
- Positive case (a real SYSTEM service is accepted) needs the service installed as LocalSystem →
  run elevated with `packaging/manage_service.ps1` (Phase 2D operator step).

### Anti-debugging (modest, standard)
`security-core/src/main.rs`: in release builds the license service refuses to start under a
debugger (`IsDebuggerPresent`), recording `DEBUGGER_DETECTED` to the local events log. Dev builds
keep debugging. This protects the authority's decisions from being single-stepped; it is a
conservative, well-known check, not heavy anti-analysis.

### Final secret scan in the release pipeline
`packaging/scan_secrets.py` walks the staged payload and fails the build on private keys, assigned
API/admin tokens, PEM private blocks, DPAPI blobs or SQLite databases; `.example` templates with
empty values pass. Wired into `build_installer.py` right before packaging. Verified on a planted-
secret tree (catches token, PEM, `.dpapi`; passes a clean tree). Complements the Phase 1
`admin-system/audit_package.py` audit of the finished EXE.

### Nuitka hardening
`packaging/build_protected.py` now compiles asset modules with `--no-pyi-file` and
`--python-flag=no_docstrings`, so the `.pyd` leaks less (no signature stub, no docstrings).

## Hooks in place — need the publisher's certificate / infrastructure to run

### Authenticode signing (`packaging/build_installer.py::authenticode_sign`)
Signs the native core and the installer with `signtool` when `AUDIO_SIGNING_CERT` (.pfx),
`AUDIO_SIGNING_PASSWORD` and optional `AUDIO_SIGNING_TIMESTAMP_URL` are set; a hardened release
(`AUDIO_RELEASE_HARDENED=1`) requires the cert. The core is signed before the manifest hashes it;
the installer is signed before its release hash is recorded. **You must obtain an identity-verified
code-signing certificate** (ideally EV, on a hardware token) — it is never in the repo. Not run here
(no cert, and `signtool` may be absent).

### Per-customer builds (`build_installer.py --customer`)
Records a per-customer tag with the release for traceability of a leaked build. Full per-build
stamping/watermarking of the shipped files is left to the watermark item below.

## Deferred — need hardware or the real pipeline (documented, not faked)

- **TPM / attestation for the lease key.** The lease key is DPAPI-sealed today. Binding it to the
  TPM (so it cannot be copied off the machine even by a local admin) needs TPM hardware and the
  Windows TBS/NCrypt platform-key APIs, which cannot be exercised reliably here. Design: generate
  the machine X25519 key in a TPM-backed NCrypt key container instead of DPAPI; everything else in
  `lease.rs` is unchanged because only key storage moves.
- **Per-stage execution context.** Still the Phase 2B limitation: the service would issue a
  short-lived context on authorize and each stage would validate it before getting the content key,
  so a direct `python worker.py` on a licensed machine gets nothing. Threading the context from the
  launcher through the orchestrator into each stage subprocess, and testing it, needs the real
  multi-stage workflow to run (RAM/pipeline) — not available here.
- **Output watermarking.** A per-customer, hard-to-remove mark in the translated text / audio so a
  leaked output traces back to a customer. Touches the export/TTS pipeline (one of which is
  mid-change on disk) and needs the pipeline to run to validate robustness.
- **Heavy obfuscation.** Beyond Rust strip+LTO (already on) and the Nuitka `.pyd` compile +
  hardening flags above, stronger control-flow obfuscation needs a commercial tool; not attempted.

## Residual risks after Phase 3 (as far as it goes here)
- Until Authenticode runs, the binaries are unsigned; integrity still protects them at runtime but
  Windows SmartScreen will warn users.
- Until the execution context is threaded, a currently-licensed machine can read assets by calling
  the worker directly; lease expiry remains the monetization gate.
- A local **administrator** can still install their own LocalSystem service; peer verification stops
  a non-admin look-alike, not an admin who controls the machine. This matches the threat model
  (slow the owner, not stop them). TPM attestation would raise this bar further.
