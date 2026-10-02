# Source and release layout

The application repository and its only Git metadata are in `audio-translates/`.
The sole Windows release entry point is `npm run package:windows` (activate
`.venv` first). It builds the native security authority, Next standalone server,
and portable Python dependencies as one installer. `npm run build` compiles the
web component only; it is not a separate app packaging workflow.

`packaging/build_security_core.py` is an internal sub-step, not another product.
Rust's Cargo files/toolchain remain necessary to build that authority. Successful
installer builds remove their own staging directory after recording the release.
Published installers and release records remain in `dist/` for licensing/admin
download history. Increment the product version before rebuilding changed code.

## Providers

- `../VieNeu-TTS-main/src/`: unchanged runtime Python source and voice assets.
  Model usage guides and upstream license stay alongside it. There is no nested
  `VieNeu-TTS-main/VieNeu-TTS-main` directory or separate vendor build setup.
- FunASR and yt-dlp run from installed packages in `.venv`, not source checkouts.
  Their upstream usage documentation and licenses are retained in their folders;
  unused development source and model-specific build systems are removed.
- NLLB weights in `../huggingface/`, ASR weights in `data/model-cache/`, and
  VieNeu/codec weights in `data/hf-cache/` are retained. They are not duplicate
  source/build outputs and must not be deleted as routine cleanup.

## Development versus shipped payload

Keep `.venv`, `node_modules`, application tests, private admin data and processing
checkpoints for development/use. They are not copied wholesale into the installer.
The packaging whitelist ships runtime components, provider source, required
dependency files, licenses and pre-generated voice samples only. Worker tests,
verification scripts, scratch directories and bytecode are excluded.

Old isolated `.next-*` builds, prior installer staging trees, installer-smoke
installs and disposable `data/verification` fixtures can be regenerated and have
been removed. The current `.next` is retained while its server is running.

Workspace cleanup reduces development disk usage, not the irreducible size of
model weights or required PyTorch runtime in an offline-capable application.

## Cleanup verification (2026-10-03)

Removed 11,314,756,625 bytes (about 11.3 GB / 10.54 GiB) from the inspected
generated builds, installer-smoke installations, staging trees, verification
fixtures and unused upstream development source. Additional obsolete documentation
build scripts and 28 empty worker tempfile directories were also removed.
These were permanent deletions; generated outputs can be rebuilt and upstream
development checkouts can be downloaded again. No local backup was kept.

35 tests passed (provider path compatibility and workflow management); the
flattened provider discovers all 25 voices. The existing workflow state file's
SHA-256 remained unchanged and the existing Studio server returned HTTP 200.
Python syntax and packaging fingerprint checks passed. A full new installer was
not built as part of cleanup, so a smaller release size has not been measured.

The running `.next-security-phase1` verification build was deliberately retained,
as was the serving `.next`. `.github/modernize/java-upgrade` is unrelated tooling
whose deletion was blocked by safety review; it requires separate approval.
Published installers/release records, model weights, active development toolchains,
application tests and real processing data were retained rather than treating
them as disposable cache.
