> Current TRANSLATION: Hy-MT2-7B Q4_K_M; see [setup](TRANSLATION_LONG.md). Qwen sections below are historical.

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
- Active Hy-MT2 weights are in `models/Hy-MT2-7B-Q4_K_M/`, downloaded directly
  with checksum/provenance and no vendor Git/source tree. ASR weights in
  `data/model-cache/` and
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

## Qwen translation replacement (2026-10-03)

The runtime uses one CPU llama-cpp-python wheel in `.venv`, not a llama.cpp
source checkout. The model folder contains only the GGUF, MODEL_CARD.md, LICENSE
and provenance.json. The only source Git metadata remains `audio-translates/.git`.
The installer whitelist now includes this verified GGUF and its license/runtime;
a previously published installer must be rebuilt with a new version to include it.

## Cleanup (2026-10-04)

The obsolete sibling translation cache and saved obsolete adapter configurations
have been removed. At that time Translation had one supported backend, Qwen GGUF;
it was replaced by Hy-MT2-1.8B Q8_0 the same day (see TRANSLATION_LONG.md).
The private sibling `../admin-system/` remains outside the product Git repository.
Both workspace and product ignore rules exclude its entire directory.

## Source layout (2026-10-04)

Frontend (Next.js). Route URLs under `app/` are unchanged; only shared code moved.

```
app/                  routes only: pages, layout, api/**/route.ts, css
components/           React components by feature
  common/ layout/ workflow/ history/ rules/ license/ voice/ settings/
lib/
  server/             node-only services: worker-client (spawns worker/<entry>.py),
                      python, security-core, jobs, history, management, license,
                      rules, artifacts, file-response, voice-previews, transcription-progress
  i18n/               translations, ui-text, localized-guides, language-context
  theme/              theme, theme-context
  shared/             pure helpers (format)
```

Import everything through the `@/` alias (`@/components/...`, `@/lib/server/...`).
Client components may import only types from `lib/server`.

Worker (Python). `worker/` is the single import root (`python312._pth` and the
dev scripts put it on `sys.path`).

```
worker/
  manage.py retry.py orchestrator.py rules.py results.py
  youtube_session.py compute_settings.py
  resources.py                               CLI entry shims (see below)
  audio_translate/                           all logic
    core/           storage, control, errors, memory_policy, license_gate,
                    providers, compute_settings, lanes (multi-workflow ledger)
    workflow/       manage, orchestrator, retry, results, stage_reset,
                    workflow_admission, postprocess (translate/moderate/TTS drivers)
    transcription/  pipeline (download, VAD, chunks), asr_runtime,
                    transcription_progress, youtube_session
    translation/    hymt_translation, translation_server
    tts/            adapters, tts_runtime, voices, voice_previews
    moderation/     rules
  config/           asr-memory.json, translation-runtime.json, tts-runtime.json
  tools/            shipped provisioning scripts (download_*, export_translation)
  dev/              verify_*, benchmark_*, smoke_e2e (not shipped)
  tests/            unit tests (not shipped)
  requirements.txt
```

Entry shims keep their file names because the native security core
(`security-core/src/main.rs`) launches `app/worker/<script>` from a fixed
allowlist (`manage.py`, `retry.py`, `orchestrator.py`) and `lib/server/worker-client.ts`
spawns the others by name. Each shim only calls
`runpy.run_module('audio_translate.<domain>.<module>', run_name='__main__')`.
Renaming or moving a shim requires rebuilding `security-core` and bumping the product version.

Dependency direction: `core` has no domain dependencies (it lazily imports
`workflow.results` for cleanup). Domain packages import `core`; `workflow`
imports every stage package. Cross-package imports use absolute paths
(`from audio_translate.core.storage import ...`).

Commands:

- Unit tests: `.venv\Scripts\python.exe -m unittest discover -s worker/tests -t worker -p "test_*.py"`
- A module as a script: `$env:PYTHONPATH="worker"; .venv\Scripts\python.exe -m audio_translate.<pkg>.<module>`
- `tools/` and `dev/` scripts run directly (`python worker/tools/download_translation_server.py`) and
  add `worker/` to `sys.path` themselves.
- Packaging copies `worker/` without `tests`, `dev`, `docs`; `components/` is part of the source hash.
- Frontend checks: `npm run lint`, `npm run check:i18n`, `npm run check:theme`.
