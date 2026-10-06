# 0. CẬP NHẬT TRẠNG THÁI (2026-10-05)

Tài liệu này được viết lần đầu ở phiên bản 1.0.2 (Qwen3, `worker/*.py` phẳng). Mã nguồn đã đổi nhiều từ đó; các mục bên dưới đã được đồng bộ lại. Số liệu "đếm từ mã" được đo lại ngày 2026-10-05; kết quả chạy test lấy từ `Agent.md` mục 4.

Thay đổi chính so với bản đầu:

- **Phiên bản 1.1.0** (`product.manifest.json`, `package.json`); `dist/` có installer 1.0.0, 1.0.1, 1.0.2, 1.1.0 và `release-*.json`. Có bằng chứng đã build; chưa có bằng chứng phát hành hay người dùng thật.
- **Dịch: Hy-MT2-1.8B Q8_0 GGUF** qua `llama-server` dùng chung nhiều slot (thay Qwen3-8B Q4_K_M, trước đó là NLLB). `QWEN_*_RESULT.md` chỉ còn là lịch sử.
- **Cấu trúc worker**: logic ở `worker/audio_translate/{core,workflow,transcription,translation,tts,moderation}/`; `worker/` chỉ giữ 7 shim (`manage`, `retry`, `orchestrator`, `rules`, `results`, `youtube_session`, `compute_settings`). Test ở `worker/tests/`, script kiểm tra ở `worker/dev/`, cấu hình ở `worker/config/`.
- **Frontend**: `app/` chỉ chứa route (28 `route.ts`, 9 `page.tsx`); component ở `components/<feature>/`; logic ở `lib/{server,i18n,theme,shared}/`.
- **License/bảo mật**: thêm `security-core/` (Rust) xác minh license, Machine ID, DPAPI, allowlist lệnh worker, dung sai đồng hồ 5 phút (`CLOCK_SKEW_SECONDS`). Xem `SECURITY_PHASE_1_RESULT.md`.
- **Tính năng mới** (chi tiết ở docs tương ứng): chọn CPU/GPU theo workflow (`COMPUTE_SETTINGS.md`), chạy nhiều workflow theo tài nguyên (`MULTI_WORKFLOW_SCHEDULER.md`), Kiểu giọng (`VOICE_STYLES.md`), xưng hô/giới tính/thuật ngữ theo thể loại (`ADDRESS_FORMS.md`), Tools nhận link YouTube và xóa khi đang chạy (`TOOLS.md`), checkpoint dịch từng đoạn và Continue (`TRANSLATION_CHECKPOINTS.md`), tiến độ 4 pha chép lời, xem trước giọng.
- **Kiểm tra gần nhất** (`Agent.md` mục 4): 287 test Python pass, 1 bỏ qua; `tsc --noEmit`, eslint, `check:i18n`, `check:theme` sạch; `next build` đủ route. Chưa build installer và chưa chạy job thật đầu-cuối sau tái cấu trúc.
- **Vẫn chưa có**: CI, benchmark chất lượng ASR/dịch/TTS, số người dùng. GPU chưa dùng được an toàn (`CALIBRATION_REVIEW.md`).

# 1. PROJECT OVERVIEW

Project Name: Audio Translate / Audio Studio (`audio-translates`, version `1.1.0`).

Project Type: Local Windows-oriented web application for converting a YouTube audio source into Chinese transcription, Vietnamese translation, rule-moderated Vietnamese text, and Vietnamese speech.

Problem / Purpose: Persist and manage a multi-stage audio processing workflow, including retry, cancellation, reprocessing, history, and saved artifacts.

Target Users: Local desktop users who provide a supported YouTube URL or use standalone conversion tools; the repository does not establish production-user counts.

Main Business Domains: Audio/video download (YouTube or file); ASR; machine translation; text replacement moderation; TTS; local workflow/history management; YouTube session management; offline machine-bound licensing; resource-aware multi-workflow scheduling; genre-specific voice style and Vietnamese address-form post-processing.

System Scale:

- Backend services: 1 Next.js server, 1 Rust `security-core` broker (license/command allowlist), and Python workers (several workflows may run concurrently, admitted by RAM/CPU/GPU/temperature); each AI stage runs in an isolated subprocess.
- Frontend apps: 1 Next.js application.
- Databases: SQLite is used for workflow numbering and per-job post-processing checkpoints; filesystem JSON/JSONL is used for job state and outputs. The separate `admin-system` also uses SQLite.
- Business modules: 5 workflow steps: DOWNLOAD, TRANSCRIPTION, TRANSLATION, MODERATION, TTS.
- Deployable components: Windows installer (`dist/AudioTranslate-1.1.0.exe` built; adoption unknown); no Docker, Kubernetes, Terraform, or cloud deployment manifests found in `audio-translates`.
- AI components: FunASR ASR/VAD/punctuation, Hy-MT2-1.8B Q8_0 GGUF translation (llama-server, shared slots), and VieNeu TTS adapters.

Main Tech Stack: TypeScript, Next.js 16, React 19, Python, Rust (security-core), FunASR, llama.cpp / llama-cpp-python (Hy-MT2), PyTorch (CPU build), VieNeu TTS, yt-dlp, FFmpeg/ffprobe, SQLite, Node.js, Windows DPAPI, Ed25519 (`cryptography`).

Repository Structure: `audio-translates/` contains the application; `worker/audio_translate/` contains processing/lifecycle code; `app/` contains routes (28 API `route.ts` files, 9 pages); `components/` holds React components; `lib/server/` bridges Next.js to Python and serves artifacts; `security-core/` (Rust) enforces licensing and the worker command allowlist; `admin-system/` and `shared-license-sdk/` are local companion repositories used for packaging/licensing. `FunASR-main/`, `VieNeu-TTS-main/`, and `yt-dlp-master/` are upstream source checkouts and are not counted as application-authored implementation evidence.

# 2. SYSTEM ARCHITECTURE

Architecture Style: Local web application with a Next.js UI/API layer, filesystem-backed job queue/state, and Python processing worker.

Service Architecture: A single persistent Next.js server launches queued Python workflow workers through the Rust security-core; a resource-aware scheduler (`workflow/scheduling.py`, `workflow_admission.py`, `core/lanes.py`) decides how many run at once; the Python orchestrator executes each stage in a separate Python subprocess. This is not a network microservice deployment.

Data Architecture: Job state is `job.json`; intermediate data/checkpoints live in a job workspace; final artifact generations are published under a separate results root. SQLite stores global workflow allocation and per-job segment checkpoints.

Communication Patterns: Browser to Next.js route handlers over HTTP; route handlers spawn Python programs with JSON stdin/stdout; worker stages communicate through files and persisted state rather than a message broker.

Authentication / Authorization Architecture: There is no user account/RBAC implementation found. Protected operations are gated by local machine-bound licenses verified in the Rust `security-core` (worker commands are allowlisted by script name). A dedicated browser profile is used only to obtain YouTube cookies for downloading.

Deployment Architecture: Local persistent Next.js process, Python environment, FFmpeg/ffprobe, model files/cache, and writable data directory. Packaging targets a Windows `.exe`; serverless deployment is explicitly excluded by README.

Important Architecture Decisions:

## ARCH-01

Decision: Use a durable, filesystem-backed workflow with a separate published-results root.

Problem: Processing can be interrupted while users need history and already completed artifacts to remain readable.

Why this approach exists: `job.json`, staged files, `outputs.json`, checksums, and atomic rename permit recovery without adding a history database.

Implementation: Workspaces reside in `data/tmp/<UUID>` (legacy `data/jobs` supported); final files publish to `RESULTS_ROOT/{workflows|tools}/<number>`. Publish validates staged copies then atomically replaces targets.

Technologies: Python, JSON/JSONL, SQLite, filesystem locks, SHA-256, `os.replace`.

Affected components: Python worker/orchestrator/results/manage modules; Next.js history and artifact routes.

Trade-offs: Local-disk coupling; local-only scheduler; no distributed queue/database.

Scale: 2 storage scopes (`workflows`, `tools`); 4 published stage groups (transcription, translation, moderation, TTS).

Result: Prior published generation is retained if a later publish copy fails, according to `test_results.py`.

Evidence:

- `audio-translates/worker/audio_translate/workflow/results.py`
- `audio-translates/worker/audio_translate/workflow/manage.py`
- `audio-translates/lib/server/history.ts`
- `audio-translates/README.md` (Saved results and History)

ROLE_FIT:
Backend: HIGH
Platform/Cloud: LOW
DevOps: MEDIUM
AI Application: MEDIUM
AI Backend: MEDIUM
Software Engineer: HIGH

## ARCH-02

Decision: Split the workflow into ordered, resumable stage subprocesses.

Problem: AI model memory and failure recovery need to be handled across download, ASR, translation, moderation, and TTS.

Why this approach exists: Each stage can persist outputs/checkpoints, be retried independently, and release model memory before the following AI stage starts.

Implementation: `orchestrator.py` locks a job, verifies predecessors, invokes itself with `--stage`, publishes successful steps, records failures, and honors cancellation signals.

Technologies: Python subprocesses, OS file locks, JSON state, SQLite checkpoints.

Affected components: `worker/audio_translate/workflow/orchestrator.py`, `control.py`, `errors.py`, `retry.py`, `postprocess.py`.

Trade-offs: A retry runs only the failed node and pending successors are scheduled later; cancellation is cooperative and waits for a model call to reach a cancellation check.

Scale: 5 ordered steps; the scheduler admits workflows by live resources (at ~4 GiB free RAM sequential is faster than parallel; see `MULTI_WORKFLOW_SCHEDULER.md`).

Result: Completed predecessors and reusable output checkpoints are not rerun on downstream failure.

Evidence:

- `audio-translates/worker/audio_translate/workflow/orchestrator.py`
- `audio-translates/worker/audio_translate/core/control.py`
- `audio-translates/lib/server/jobs.ts`
- `audio-translates/README.md` (Node errors and retry)

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: MEDIUM
AI Application: HIGH
AI Backend: HIGH
Software Engineer: HIGH

# 3. BACKEND ENGINEERING EVIDENCE

## BE-01

Feature / Component: Next.js HTTP API for workflow, history, artifacts, rules, tools, license, voices, and YouTube settings.

Problem: UI requires operations and persisted state for a local processing application.

Technical Contribution: Repository implements 28 `route.ts` handlers, including job create/get/retry/cancel/pause/continue/reprocess/step/error/transcript/artifact endpoints, history endpoints, rules CRUD, tools, license, voices, compute settings, and YouTube settings.

Implementation: Route handlers validate request body size/JSON where applicable and use `lib` modules to invoke Python commands or serve files.

Technology: Next.js route handlers, TypeScript, Node.js child processes.

Architecture / Design Decision: Next.js is API/UI boundary and reaches the worker only through `worker-client.ts` and `security-core` (shim names act as an allowlist; do not rename); workflow state and AI work remain in Python.

Services involved: Local Next.js server and Python worker.

Data involved: JSON job metadata, output manifests, JSONL/Markdown/WAV files.

Security involved: UUID validation, bounded request/file reads, license checks on protected operations.

Scale / Metric: 28 route files; UNKNOWN request traffic.

Technical Result: APIs exist for all five workflow steps and saved-history operations.

Trade-off / Limitation: No external API authentication or multi-user access control found.

Evidence:

- `audio-translates/app/api/`
- `audio-translates/lib/server/jobs.ts`
- `audio-translates/lib/server/management.ts`

USER_CONTRIBUTION: NEED_USER_CONFIRMATION

ROLE_FIT:
Backend: HIGH
Platform/Cloud: LOW
DevOps: LOW
AI Application: MEDIUM
AI Backend: MEDIUM
Software Engineer: HIGH

## BE-02

Feature / Component: Workflow lifecycle, retry, cancellation, and persisted errors.

Problem: Long-running multi-stage tasks can fail or be cancelled without discarding valid completed work.

Technical Contribution: Persisted step states include attempts, retry counts, timestamps, duration, output manifest status, and sanitized error data. Retry validates state and targets a named step.

Implementation: Orchestrator uses a per-job OS lock; `errors.py` classifies/redacts exceptions; `control.py` stores a cancellation signal and removes incomplete artifacts for the affected step.

Technology: Python, JSON, OS locks, subprocesses.

Architecture / Design Decision: Filesystem state is the source of truth rather than in-memory worker state.

Services involved: Next.js scheduler/API and Python worker.

Data involved: `job.json`, `errors.jsonl`, `working/cancel.signal`, step manifests/checkpoints.

Security involved: Error redaction and lock-based prevention of concurrent job ownership.

Scale / Metric: 5 lifecycle step types; retry endpoint returns 202 for accepted retries and 409 for invalid state/lock per verification code.

Technical Result: Tests cover retry isolation and that completed published results are not deleted by a retry.

Trade-off / Limitation: Cancellation is cooperative rather than immediate process termination.

Evidence:

- `audio-translates/worker/audio_translate/workflow/orchestrator.py`
- `audio-translates/worker/audio_translate/core/errors.py`
- `audio-translates/worker/audio_translate/core/control.py`
- `audio-translates/worker/audio_translate/workflow/retry.py`
- `audio-translates/worker/tests/test_results.py`
- `audio-translates/worker/dev/verify_error_http.py`

USER_CONTRIBUTION: NEED_USER_CONFIRMATION

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: MEDIUM
AI Application: MEDIUM
AI Backend: HIGH
Software Engineer: HIGH

## BE-03

Feature / Component: History/artifact retrieval and file streaming.

Problem: Large saved audio and transcripts must be browsed/downloaded without generating duplicate copies or exposing arbitrary paths.

Technical Contribution: Manifest-based history resolves only known file IDs. Preview reads are bounded; WAV/download responses implement HTTP byte ranges.

Implementation: History list filters/searches/sorts known job metadata; file resolution validates UUID/scope and uses published `outputs.json`; `file-response.ts` handles 206/416 and stream cancellation.

Technology: TypeScript, Node filesystem APIs, HTTP Range.

Architecture / Design Decision: Saved published artifacts, not working files, are exposed by file APIs.

Services involved: Next.js history/artifact routes and Python management/results modules.

Data involved: `job.json`, `outputs.json`, JSONL/Markdown/WAV.

Security involved: Real-path containment including symlink checks; no absolute paths in manifest; traversal tests.

Scale / Metric: Preview limit 64 KiB/request; verification fixture streams a 64 MiB WAV with checksum; range tests cover 206 and 416.

Technical Result: Verification script asserts traversal/missing file blocking and range behavior.

Trade-off / Limitation: History is local filesystem based, not indexed by a query database.

Evidence:

- `audio-translates/lib/server/history.ts`
- `audio-translates/lib/server/file-response.ts`
- `audio-translates/worker/audio_translate/workflow/manage.py`
- `audio-translates/worker/dev/verify_history_http.py`

USER_CONTRIBUTION: NEED_USER_CONFIRMATION

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: LOW
AI Application: LOW
AI Backend: MEDIUM
Software Engineer: HIGH

# 4. PLATFORM / CLOUD EVIDENCE

## PLAT-01

Problem: Package a local application with runtime dependencies and durable per-user state on Windows.

Infrastructure / Platform Component: Windows installer/build integration and configurable local runtime paths.

Implementation: Product manifest (version 1.1.0) declares `packaging/build_installer.py` and `dist/AudioTranslate-1.1.0.exe`; `packaging/build_security_core.py` builds the Rust core; `dist/` holds installers 1.0.0–1.1.0 and release JSON files. README documents packaged Node, Python, FFmpeg and CPU inference dependencies; user data persists under `LocalAppData`.

Technology: Python packaging scripts, C# installer/bootstrap source, Rust (`security-core`), Node.js, Python, FFmpeg, Windows.

Architecture Decision: Persistent local service rather than serverless execution.

Deployment Environment: Windows 10/11 as documented; local localhost web UI.

Services affected: Next.js server, worker, models, license state, YouTube browser profile.

Automation: `npm run package:windows` calls the Python installer build script.

Security: Packaging manifest carries public configuration; licensing SDK uses machine-scope DPAPI for local state.

Scale: 1 installer artifact path/version documented; UNKNOWN installations.

Result: Build entry points exist and installers up to 1.1.0 were built. No build was made after the 2026-10-04 restructure and Hy-MT2 switch; raise the version before the next build. Shipping/adoption evidence: none.

Trade-off: Requires persistent local runtime, writable disk, model caches, and FFmpeg; not serverless.

Evidence:

- `audio-translates/product.manifest.json`
- `audio-translates/package.json`
- `audio-translates/packaging/build_installer.py`
- `audio-translates/packaging/installer.cs`
- `audio-translates/packaging/build_security_core.py`
- `audio-translates/README.md` (Licensing and universal Windows installer)

ROLE_FIT:
Backend: MEDIUM
Platform/Cloud: MEDIUM
DevOps: MEDIUM
AI Application: MEDIUM
AI Backend: MEDIUM
Software Engineer: MEDIUM

## PLAT-02

Problem: Configure per-environment model/runtime/data locations without hardcoding machine paths.

Infrastructure / Platform Component: Environment-based configuration.

Implementation: `.env.example` and `worker/config/*.json` define overrides for Python binary, results/data roots, YouTube session, CPU/CUDA FunASR, ASR/translation/TTS live RAM thresholds, Hy-MT2 model/server/context/batch, VieNeu source/device/voice/precision, and isolated verification build/data roots.

Technology: Environment variables, Node.js, Python.

Architecture Decision: Defaults to CPU and local project data; the CPU/GPU choice is stored per workflow (`data/settings/compute.json`, frozen at first run). The dev `.venv` has CPU-only torch, so GPU mode is not usable yet.

Deployment Environment: Local Windows/Linux/macOS development paths are documented; installer target is Windows.

Services affected: Next.js, worker, ASR, translation, TTS, browser session, license state.

Automation: Environment isolation is used by documented HTTP acceptance commands.

Security: Cookie/session roots are outside repository/installer by default; cookie config is documented as private.

Scale: `HY_MT_BATCH_SIZE` is validated at ≤ 8 (default 4); translation slots grow from 1 by live resource observation (start 3.5 GiB free, reserve 2 GiB, +0.4 GiB per slot, CPU/GPU 85%, 85 °C).

Result: Config loading exists; no cloud provisioning implementation found.

Trade-off: Manual local environment setup remains necessary in source-run mode.

Evidence:

- `audio-translates/.env.example`
- `audio-translates/worker/config/`
- `audio-translates/worker/audio_translate/tts/adapters.py`
- `audio-translates/lib/server/python.ts`

ROLE_FIT:
Backend: MEDIUM
Platform/Cloud: MEDIUM
DevOps: MEDIUM
AI Application: HIGH
AI Backend: HIGH
Software Engineer: MEDIUM

# 5. DEVOPS / CI-CD EVIDENCE

## DEVOPS-01

Workflow: Local build, lint, unit test, and isolated HTTP verification commands.

Trigger: Manual commands documented in README and `Agent.md`; no GitHub Actions workflow was found.

Problem: Validate TypeScript build/lint and Python workflow behavior without mixing verification artifacts with normal data.

Steps: Run `npx tsc --noEmit`, `npm run lint`, `npm run check:i18n`, `npm run check:theme`, `npm run build`, Python unittest discovery, optional real-model smoke test, then start Next.js with isolated `AUDIO_DATA_DIR`/`AUDIO_NEXT_DIST_DIR` for HTTP verification.

Tools: npm, ESLint, Next.js build, Python unittest, custom verification scripts.

Build: `next build` through `npm run build`.

Test: 25 Python `test_*.py` modules in `worker/tests/` (287 tests pass, 1 skipped on 2026-10-05, run with `python -m unittest discover -s worker/tests -t worker -p "test_*.py"`); custom scripts in `worker/dev/` include `verify_http.py`, `verify_error_http.py`, `verify_history_http.py`, and `verify_management_http.py`.

Deploy: Windows package build command exists; no CI/CD deployment pipeline found.

Failure handling: Worker error persistence, retry/fix-guide support, and isolated verification data paths are implemented.

Environment: `.env.example` and README specify Node 22+, Python 3.11/3.12, FFmpeg/ffprobe, and virtualenv setup.

Automation achieved: Build/test commands and Python verification scripts exist; continuous execution is UNKNOWN.

Scale: 25 worker unit-test modules (287 tests); 4 named HTTP verification scripts; `packaging/test_security_phase1.py` (8/8 before the Hy-MT2 switch, not rerun).

Result: `Agent.md` section 4 records the 2026-10-04/05 runs (unit tests, `tsc`, eslint, i18n/theme checks, `next build`); `IMPLEMENTATION_RESULT.md` records the earlier feature verification. No CI executes them. `worker/dev/verify_notice.cjs` has been broken since before the restructure.

Evidence:

- `audio-translates/package.json`
- `audio-translates/README.md` (Verification / Verify)
- `audio-translates/worker/tests/test_*.py`
- `audio-translates/worker/dev/verify_*.py`
- `audio-translates/IMPLEMENTATION_RESULT.md`

ROLE_FIT:
Backend: MEDIUM
Platform/Cloud: MEDIUM
DevOps: HIGH
AI Application: MEDIUM
AI Backend: MEDIUM
Software Engineer: HIGH

# 6. AI / LLM / MCP EVIDENCE

No LLM, OpenAI API, MCP server/tool, embeddings, vector database, RAG, OCR, or face-recognition implementation was found in the application code. The AI evidence below concerns ASR, neural machine translation, and TTS.

## AI-01

Feature: YouTube audio to timestamped Chinese transcription.

User Problem: Convert a YouTube source into Chinese text with timestamps.

Purpose: Download audio-only stream, decode it, identify speech, and transcribe bounded audio chunks.

Input: Validated YouTube URL; optional dedicated YouTube browser session/cookies.

Output: `transcript.zh.jsonl` with `start_ms`, `end_ms`, `text`, plus Markdown transcript.

AI Model / API / Library: FunASR `AutoModel`; aliases `fsmn-vad`, `paraformer-zh`, `ct-punc`.

Processing Pipeline: yt-dlp `bestaudio` download → FFmpeg mono 16 kHz PCM → 200 ms streaming VAD frames → chunks capped near 30 seconds → FunASR with sentence timestamps → timestamp shifting/deduplication → atomic JSONL/Markdown output.

Backend Service: Python pipeline/orchestrator worker.

API: Job routes under `app/api/jobs`.

Database / Storage: Job workspace/checkpoint files and published results.

Vector Database: NONE.

Authentication: YouTube profile/cookie support only for source access; no application user authentication.

Authorization: License gate protects processing.

MCP Integration: NONE found.

Business Service Integration: Local workflow/history service.

Deployment: Local CPU default; `FUNASR_DEVICE=cuda:0` configurable.

Scale: 16 kHz PCM; 200 ms VAD frame; 30,000 ms maximum chunk; 2,500 ms overlap at forced continuous-speech boundaries; 6-second audio tail retained for overlap.

Measured Accuracy / Performance: UNKNOWN.

Result: Pipeline writes per-chunk JSON checkpoints and excludes overlapping output based on timestamp ownership.

Limitations: Live YouTube access depends on network and YouTube policy; README documents 429/sign-in cases.

Evidence:

- `audio-translates/worker/audio_translate/transcription/pipeline.py`
- `audio-translates/worker/audio_translate/workflow/orchestrator.py`
- `audio-translates/worker/tests/test_pipeline.py`
- `audio-translates/README.md` (Pipeline)

ROLE_FIT:
Backend: HIGH
Platform/Cloud: LOW
DevOps: LOW
AI Application: HIGH
AI Backend: HIGH
Software Engineer: HIGH

## AI-02

Feature: Chinese-to-Vietnamese machine translation.

User Problem: Produce Vietnamese text from the Chinese transcript without silent truncation, drift into neighbouring lines, or exhausting machine RAM.

Purpose: Translate each subtitle segment while preserving ordering/timestamp-associated records, with stable names and correct pronouns.

Input: `transcript.zh.jsonl` text records.

Output: `transcript.vi.jsonl` and Markdown output.

AI Model / API / Library: Hy-MT2-1.8B Q8_0 GGUF served by a shared `llama-server` (CPU build; GPU would need a CUDA build via `HY_MT_SERVER_PATH`, otherwise embedded `llama-cpp-python` with 1 slot).

Processing Pipeline: freeze settings per job → official zh→xx prompt without context (a 512-char context made the 1.8B model translate the context itself) → up to 3 passes with changed instruction/temperature/seed (`natural` → `conversational` → `literal`), never feeding the bad draft back → token budget `48 + 6 × source chars` → for styled jobs: sentence-level grouping with `<sN>` tags split back by timestamp, per-job Hán-Việt name glossary (`working/name-glossary.json`), character table, 他/她 fixing and genre lexicon → per-row quarantine (stop after 5 consecutive failed rows) → SQLite checkpoint per segment.

Backend Service: `worker/audio_translate/translation/{hymt_translation,translation_server,names,lexicon,source_cleanup}.py`, `workflow/postprocess.py`, `core/scaling.py`.

API: Workflow job and standalone tool routes.

Database / Storage: Per-job `working/postprocess.sqlite3`, JSONL/Markdown outputs, SHA-256 completion marker.

Vector Database: NONE.

Authentication: License gate.

Authorization: No user/RBAC authorization found.

MCP Integration: NONE found.

Business Service Integration: Feeds moderation and TTS stages.

Deployment: CPU default; resource policy in `worker/config/translation-runtime.json`.

Scale: Defaults source tokens 768, output tokens 1536, context 4096, batch 4 (max 8); live scaling from 1 slot (start 3.5 GiB free, reserve 2 GiB, +0.4 GiB/slot). Measured on the dev machine: 1x ≈ 2.17 GiB RAM, each extra slot ≈ 0.25 GiB.

Measured Accuracy / Performance: no quality benchmark. Measured speed (workflow 000007, 1048 rows, 4 slots, 0 failed rows): about 12 minutes; each row 0.5–2 s after the prompt fix (old prompt 6–7 s, bad rows about 50 s; about 48 min for 567 rows). A 150-row styled run produced 38 groups/141 rows with 0 fallbacks and consistent names. Sources: `Agent.md` open issue 1, `TRANSLATION_CHECKPOINTS.md`, `ADDRESS_FORMS.md`.

Result: Rows with output length > max(80, 12 × source chars) are rejected as drift (`output_problem`); checkpoint keys are unchanged so Resume keeps translated rows.

Limitations: 1.8B model quality is limited; Hy-MT2-7B deferred for resource reasons; new lexicon entries not all tested on the real model; no full end-to-end reprocess with the styled mode yet.

Evidence:

- `audio-translates/worker/audio_translate/translation/hymt_translation.py`
- `audio-translates/worker/audio_translate/translation/translation_server.py`
- `audio-translates/worker/audio_translate/workflow/postprocess.py`
- `audio-translates/worker/config/translation-runtime.json`
- `audio-translates/docs/TRANSLATION_CHECKPOINTS.md`
- `audio-translates/docs/TRANSLATION_LONG.md`
- `audio-translates/.env.example`

ROLE_FIT:
Backend: MEDIUM
Platform/Cloud: LOW
DevOps: LOW
AI Application: HIGH
AI Backend: HIGH
Software Engineer: HIGH

## AI-03

Feature: Rule moderation and Vietnamese speech synthesis.

User Problem: Apply user-maintained literal substitutions before generating Vietnamese narration.

Purpose: Create a moderated transcript and a continuous WAV while enabling resumable per-segment TTS.

Input: Vietnamese transcript plus persisted replacement rules; selected VieNeu voice.

Output: Moderated JSONL/Markdown, replacement count JSON, segment WAVs/manifest, continuous `voice.vi.wav`.

AI Model / API / Library: VieNeu `Vieneu(mode="v3turbo")` and `infer_stream`; `soundfile`.

Processing Pipeline: Rules snapshot under lock → NFC, literal longest-match non-cascading replacements → SQLite checkpoints → TTS only reads moderated JSONL → validate 48 kHz mono PCM16 segments → concatenate in manifest order.

Backend Service: `worker/audio_translate/moderation/{rules,address,flow}.py`, `workflow/postprocess.py`, `tts/{adapters,tts_runtime,voice_styles}.py`.

API: `/api/rules`, `/api/rules/[id]`, job/tool endpoints, `/api/voices`.

Database / Storage: Rules JSON, per-job SQLite checkpoints, JSONL/Markdown/WAV manifests.

Vector Database: NONE.

Authentication: License gate.

Authorization: Same OS lock causes concurrent rule writes to return 409 while moderation snapshots/runs.

MCP Integration: NONE found.

Business Service Integration: TTS is downstream of moderation in the workflow.

Deployment: Local VieNeu source adapter, CPU default (`VIENEU_DEVICE=cuda` exists but still uses CPU heuristics); worker pool adds +1 worker after 10 s stable and keeps it only if chars/s improves (`core/scaling.py`, `TTS_CPU.md`).

Scale: TTS uses 48,000 Hz, mono, PCM_16 output; `infer_stream` max chars 256 and max new frames 1000; code chooses RF64 if normal RIFF size would exceed 4 GiB.

Measured Accuracy / Performance: UNKNOWN.

Result: Completed WAVs may be reused only after fingerprint/hash validation; original Vietnamese transcript is not rewritten by moderation.

Limitations: Rule matching is literal and case-sensitive, not semantic/AI moderation; no quality benchmark found. For jobs with a Voice style (Default/Drama/Survival/Rebirth), moderation also fixes pronouns at sentence start (`moderation/address.py`, profiles in `worker/config/address-profiles.json`) and TTS applies per-style voice, sentence merging, atempo speed and pauses measured from sample videos (`VOICE_STYLES.md`, `ADDRESS_FORMS.md`); not yet verified on a full real workflow.

Evidence:

- `audio-translates/worker/audio_translate/moderation/rules.py`
- `audio-translates/worker/audio_translate/workflow/postprocess.py`
- `audio-translates/worker/audio_translate/tts/adapters.py`
- `audio-translates/worker/audio_translate/tts/tts_runtime.py`
- `audio-translates/worker/tests/test_postprocess.py`
- `audio-translates/worker/tests/test_voice_styles.py`
- `audio-translates/worker/tests/test_address.py`

ROLE_FIT:
Backend: HIGH
Platform/Cloud: LOW
DevOps: LOW
AI Application: HIGH
AI Backend: HIGH
Software Engineer: HIGH

# 7. DATA / DATABASE EVIDENCE

## DATA-01

Problem: Allocate non-reused workflow numbers and retain resumable per-segment post-processing state.

Data Design: Global workflow registry separated from each job's inference checkpoint database.

Database: SQLite.

Implementation: `manage.py` creates/uses `workflow-registry.sqlite3`; `Checkpoints` creates a `segments(stage, idx, fingerprint, output)` table with `(stage, idx)` primary key and `PRAGMA synchronous=FULL`.

Ownership: Local application data directory.

Cross-service strategy: No cross-service database references; Next.js and Python share local files/SQLite.

Scale: 2 SQLite use cases; workflow number is a positive integer and output naming is zero-padded in code.

Result: Stage outputs can be reused when matching fingerprints and file hashes are present.

Trade-off: SQLite/filesystem local state does not provide distributed ownership or multi-host coordination.

Evidence:

- `audio-translates/worker/audio_translate/workflow/manage.py`
- `audio-translates/worker/audio_translate/workflow/postprocess.py`
- `audio-translates/worker/audio_translate/core/storage.py`

ROLE_FIT:
Backend: HIGH
Platform/Cloud: LOW
DevOps: LOW
AI Application: MEDIUM
AI Backend: HIGH
Software Engineer: HIGH

## DATA-02

Problem: Keep completed output data safe during retries, restarts, and history backfill.

Data Design: Workspace versus immutable-style published generation, manifest metadata, staged files, hashes, and atomic replacement.

Database: Filesystem JSON/JSONL plus SQLite checkpoints.

Implementation: `results.py` stages outside results, writes/fsyncs metadata, retries Windows `PermissionError` replacements up to 8 times, and prevents overlap between results root and workspace roots.

Ownership: Local application results root.

Cross-service strategy: Published manifest is the contract consumed by Next.js history/file APIs.

Scale: 8 configured output types across 4 workflow stage groups.

Result: Test covers copy failure preserving previous published files.

Trade-off: No external object store/versioning service.

Evidence:

- `audio-translates/worker/audio_translate/workflow/results.py`
- `audio-translates/worker/tests/test_results.py`
- `audio-translates/lib/server/history.ts`

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: MEDIUM
AI Application: MEDIUM
AI Backend: HIGH
Software Engineer: HIGH

# 8. SECURITY / AUTH EVIDENCE

## SEC-01

Security Problem: Prevent arbitrary path exposure/deletion from history and lifecycle APIs.

Threat / Risk being handled: Path traversal, symlink/junction escape, invalid IDs, exposing unlisted/working artifacts.

Architecture: Python validates storage paths/manifests; Next.js resolves known file IDs and streams only resolved published files.

Implementation: UUID checks, `Path.resolve()` containment checks, symlink/junction rejection in `safe_directory`, published-manifest lookup, and range response handling.

Token / Protocol: HTTP file Range support; no user identity token.

Trust Boundary: API request → validated ID/file ID → published results root.

Services affected: History, tool file, job artifact routes; worker management/results.

Result: `verify_history_http.py` asserts path traversal/missing-file blocking.

Limitations: No general user authentication/authorization layer was found.

Evidence:

- `audio-translates/worker/audio_translate/workflow/manage.py`
- `audio-translates/worker/audio_translate/workflow/results.py`
- `audio-translates/lib/server/history.ts`
- `audio-translates/lib/server/file-response.ts`
- `audio-translates/worker/dev/verify_history_http.py`

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: LOW
AI Application: LOW
AI Backend: MEDIUM
Software Engineer: HIGH

## SEC-02

Security Problem: Gate protected local features and bind licenses to one Windows machine.

Threat / Risk being handled: Unlicensed use, token tampering, license copied to another machine, local clock rollback.

Architecture: Rust `security-core` (`security-core/src/{main,license,windows}.rs`, `trust-anchor.json`) verifies license, Machine ID and DPAPI state and gates workflow/retry; Python `core/license_gate.py` is the worker-side check. Product embeds/configures a public root key; shared SDK verifies Ed25519-signed machine-bound tokens and stores state through Windows DPAPI. Protected workflow checks use trusted Internet time according to SDK README.

Implementation: `license_gate.py` exposes worker check/activation/status; Next.js calls `lib/server/security-core.ts` and `license.ts` before protected routes; `security-core` compares trusted Internet time with the last verified time using a 5-minute tolerance (`CLOCK_SKEW_SECONDS`, added 2026-10-04 after a transient `CLOCK_ROLLBACK` between stages); crypto code signs/verifies canonical payloads with `Ed25519PublicKey`.

Token / Protocol: `ed25519-v1` license scheme; HTTPS date-source quorum is described by SDK README.

Trust Boundary: Local product process/SDK boundary; private keys are not in product SDK.

Services affected: Job/tool/reprocess endpoints, worker stage updates, file preview/playback policy, admin companion.

Result: `admin-system/test_licensing.py` contains tests for expiration, clock rollback, machine claim, token sequence, and offline verification.

Limitations: Phase 1 keeps residual risk from replacing the binary/backend and from running models outside the app (`SECURITY_PHASE_1_RESULT.md`). SDK README states privileged verifier patching, complete hardware identity spoofing, or rolling back all encrypted state are outside its guarantees; no remote revocation server is implemented.

Evidence:

- `audio-translates/worker/audio_translate/core/license_gate.py`
- `audio-translates/security-core/src/license.rs`
- `audio-translates/security-core/src/main.rs`
- `audio-translates/lib/server/license.ts`
- `audio-translates/docs/SECURITY_PHASE_1_RESULT.md`
- `audio-translates/product.manifest.json`
- `audio-translates/packaging/test_security_phase1.py`
- `shared-license-sdk/license_sdk/crypto.py`
- `shared-license-sdk/README.md`
- `admin-system/test_licensing.py`

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: MEDIUM
AI Application: LOW
AI Backend: MEDIUM
Software Engineer: HIGH

## SEC-03

Security Problem: Use YouTube authentication without reading a user's regular browser profile or returning cookie values through the API.

Threat / Risk being handled: Broader browser-profile access and credential leakage into config/API responses.

Architecture: Separate Edge/Chrome profile under user local data; random loopback DevTools endpoint; only non-expired `youtube.com` cookies are materialized in memory for yt-dlp.

Implementation: Starts browser with dedicated `--user-data-dir`, `--remote-debugging-port=0`, and `--remote-debugging-address=127.0.0.1`; filters cookies by domain and returns status metadata rather than cookie values.

Token / Protocol: Browser DevTools WebSocket on loopback; HTTP cookies passed to yt-dlp in memory.

Trust Boundary: Dedicated local browser profile to worker downloader.

Services affected: YouTube settings API, worker download pipeline.

Result: Tests assert that synthetic cookie values do not appear in persisted connection metadata.

Limitations: YouTube can expire/revoke a session or require additional verification.

Evidence:

- `audio-translates/worker/audio_translate/transcription/youtube_session.py`
- `audio-translates/worker/audio_translate/transcription/pipeline.py`
- `audio-translates/worker/tests/test_youtube_session.py`
- `audio-translates/README.md` (YouTube authentication)

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: LOW
AI Application: LOW
AI Backend: MEDIUM
Software Engineer: HIGH

# 9. TESTING / QUALITY EVIDENCE

Unit Tests:

Purpose: Validate pipeline boundaries/configuration, post-processing, results publication, errors, management, YouTube session, ASR/translation/TTS runtimes, scaling/admission/lanes, compute settings, voice styles, address forms, names, tools and lifecycle/resume behavior.

Technology: Python `unittest` and mocks/fake adapters.

What is verified: Examples include audio-only downloader settings, VAD chunks/overlap, output deduplication, translation/moderation/TTS checkpoint behavior, locks, result publication, safe management operations, and session metadata handling.

Where executed: `python -m unittest discover -s worker/tests -t worker -p "test_*.py"` — 287 tests pass, 1 skipped (2026-10-05, 3 consecutive runs).

Evidence:

- `audio-translates/worker/tests/test_pipeline.py`
- `audio-translates/worker/tests/test_postprocess.py`
- `audio-translates/worker/tests/test_results.py`
- `audio-translates/worker/tests/test_errors.py`
- `audio-translates/worker/tests/test_management.py`
- `audio-translates/worker/tests/test_youtube_browser.py`
- `audio-translates/worker/tests/test_youtube_session.py`
- plus 19 more modules in `worker/tests/` (ASR/translation/TTS runtime, scaling, lanes, memory policy, admission, lifecycle, resume, compute settings, voice styles/previews, address, names, styled translation, tools, providers, transcription progress)

Integration Tests:

Purpose: Exercise real model adapters in an end-to-end smoke workflow.

Technology: Python script.

What is verified: Repository contains `smoke_e2e.py`; README describes it as a real-model smoke test isolated from Studio data.

Where executed: `python worker/dev/smoke_e2e.py`.

Evidence:

- `audio-translates/worker/dev/smoke_e2e.py`
- `audio-translates/README.md`

API Contract Tests:

Purpose: Verify local HTTP API behavior with isolated app data.

Technology: Python HTTP verification scripts.

What is verified: Rules CRUD/lock, persisted workflow state, retry errors, artifacts/history, range responses, and management/license state paths.

Where executed: Against a locally started Next.js server on documented port 3001.

Evidence:

- `audio-translates/worker/dev/verify_http.py`
- `audio-translates/worker/dev/verify_error_http.py`
- `audio-translates/worker/dev/verify_history_http.py`
- `audio-translates/worker/dev/verify_management_http.py`

Authentication / Security Tests:

Purpose: Check licensing behavior, session secret non-persistence, path traversal blocking, and rule locking.

Technology: Python `unittest` plus HTTP verification.

What is verified: License test suite exists in companion admin repository; API verification includes traversal/missing files and lock behavior.

Where executed: Local test commands; CI execution UNKNOWN.

Evidence:

- `admin-system/test_licensing.py`
- `audio-translates/worker/tests/test_youtube_session.py`
- `audio-translates/worker/dev/verify_history_http.py`
- `audio-translates/worker/dev/verify_error_http.py`

Database Migration Tests: `test_management.py` covers management/migration-related behavior; exact migration coverage percentage UNKNOWN.

PostgreSQL Integration Tests: NONE found.

Frontend Tests: No browser-component test framework found; static gates are `npx tsc --noEmit`, eslint, `npm run check:i18n`, `npm run check:theme` (clean on 2026-10-04) and `next build`. `worker/dev/verify_format.cjs` is a Node assertion script for format-related UI/source behavior; `IMPLEMENTATION_RESULT.md` reports browser checks; `worker/dev/verify_notice.cjs` is broken (missing `useLanguage` mock).

Type Checking: `npx tsc --noEmit` is run manually (clean); no npm script wraps it.

CI Quality Gates: No GitHub Actions or other CI workflow files found.

# 10. ENGINEERING CHALLENGES

## CHALLENGE-01

Problem: Prevent duplicated/misaligned ASR text when VAD must split continuous speech.

Affected Components: FFmpeg decode, VAD, FunASR transcription, transcript merge.

Root Cause: Forced chunk boundaries can overlap to preserve speech context.

Technical Decision: Use overlap only at forced boundaries; assign timestamp ownership and suppress rows largely contained/overlapping a previous row.

Solution: Store chunks with `own_start`/`own_end`, filter by midpoint ownership, merge ordered chunk output, and reject duplicate timestamp regions.

Technology: Python, FunASR, FFmpeg, JSON checkpoints.

Result: Unit tests cover VAD chunk/overlap behavior; performance/accuracy outcome UNKNOWN.

Trade-off: Overlap still consumes additional inference at forced boundaries.

Evidence:

- `audio-translates/worker/audio_translate/transcription/pipeline.py`
- `audio-translates/worker/tests/test_pipeline.py`

Needs User Context: NO

ROLE_FIT:
Backend: MEDIUM
Platform/Cloud: LOW
DevOps: LOW
AI Application: HIGH
AI Backend: HIGH
Software Engineer: HIGH

## CHALLENGE-02

Problem: Avoid losing completed artifacts when retrying/reprocessing or when publishing fails.

Affected Components: Worker lifecycle, outputs, history/file API.

Root Cause: Multi-step processing can fail after valid predecessor output exists; copying final outputs can fail midway.

Technical Decision: Separate workspace from published results, publish step outputs atomically, and preserve valid checkpoints/predecessors.

Solution: Stage/validate/copy/checksum artifacts, replace atomically, expose manifest-published outputs, and target retries at failed steps.

Technology: Python filesystem APIs, hashes, JSON manifests, SQLite checkpoints.

Result: `test_results.py` explicitly covers prior-output preservation after an atomic-copy failure and retry behavior.

Trade-off: Retaining legacy/published generations can require additional disk space.

Evidence:

- `audio-translates/worker/audio_translate/workflow/results.py`
- `audio-translates/worker/audio_translate/workflow/orchestrator.py`
- `audio-translates/worker/tests/test_results.py`
- `audio-translates/IMPLEMENTATION_RESULT.md`

Needs User Context: NO

ROLE_FIT:
Backend: HIGH
Platform/Cloud: MEDIUM
DevOps: MEDIUM
AI Application: MEDIUM
AI Backend: HIGH
Software Engineer: HIGH

## CHALLENGE-03

Problem: Prevent rule edits from changing results during a moderation run.

Affected Components: Rules API, moderation worker, persisted outputs.

Root Cause: Concurrent CRUD could otherwise alter rule inputs partway through processing.

Technical Decision: One shared OS lock protects rule CRUD and the moderation run; first snapshot is persisted for resumed work.

Solution: `ReplacementRules.locked()` wraps reads/writes; moderation writes `replacement-rules.snapshot.json`; API returns a locked result/409 during contention.

Technology: Python file locks, JSON, NFC normalization, regex literal alternatives.

Result: Test suite includes cross-process lock and crash-release cases.

Trade-off: Rule edits are unavailable for the duration of moderation.

Evidence:

- `audio-translates/worker/audio_translate/moderation/rules.py`
- `audio-translates/worker/audio_translate/workflow/postprocess.py`
- `audio-translates/worker/tests/test_postprocess.py`

Needs User Context: NO

ROLE_FIT:
Backend: HIGH
Platform/Cloud: LOW
DevOps: LOW
AI Application: MEDIUM
AI Backend: HIGH
Software Engineer: HIGH

# 11. VERIFIED METRICS

| Metric | Value | Type | Evidence |
|---|---:|---|---|
| Workflow step types | 5 | SCALE | `worker/audio_translate/core/errors.py` (`STEPS`) |
| API route files | 28 | COVERAGE | Count of `app/api/**/route.ts` (2026-10-05) |
| Worker unit-test modules | 25 | COVERAGE | Count of `worker/tests/test_*.py` |
| Worker unit tests passing | 287 (1 skipped) | COVERAGE | `Agent.md` section 4, 2026-10-05 |
| HTTP verification scripts | 4 | COVERAGE | `worker/dev/verify_http.py`, `verify_error_http.py`, `verify_history_http.py`, `verify_management_http.py` |
| VAD frame duration | 200 ms | OTHER | `worker/audio_translate/transcription/pipeline.py` (`FRAME_MS`) |
| Maximum ASR chunk duration | 30,000 ms | OTHER | `worker/audio_translate/transcription/pipeline.py` (`MAX_CHUNK_MS`) |
| Forced-boundary ASR overlap | 2,500 ms | OTHER | `worker/audio_translate/transcription/pipeline.py` (`OVERLAP_MS`) |
| ASR PCM sample rate | 16,000 Hz | OTHER | `worker/audio_translate/transcription/pipeline.py` (`RATE`) |
| Translation batch range | ≤ 8, default 4 | OTHER | `translation/hymt_translation.py`, `.env.example` |
| Translation source/output token limits | 768 / 1536 (context 4096) | OTHER | `translation/hymt_translation.py`, `.env.example` |
| Translation RAM, 1 slot / each extra slot | ≈ 2.17 GiB / ≈ 0.25 GiB | MEASURED | `Agent.md` section 2 |
| ASR peak RAM, 1 worker | ≈ 5.17 GiB RSS | MEASURED | `Agent.md` section 2, `ASR_CPU.md` |
| Translation speed, workflow 000007 | 1048 rows in about 12 min, 4 slots, 0 failed rows (old prompt: 567 rows in about 48 min) | MEASURED | `Agent.md` open issue 1 |
| TTS sample rate | 48,000 Hz | OTHER | `tts/adapters.py`, `worker/audio_translate/workflow/postprocess.py` |
| History preview maximum | 64 KiB/request | OTHER | `README.md` (Saved results and History) |
| History verification streamed WAV fixture | 64 MiB | COVERAGE | `worker/dev/verify_history_http.py` |
| Result publication Windows replace attempts | 8 | OTHER | `worker/audio_translate/workflow/results.py` |

No measured model accuracy (WER/BLEU/MOS), active users, production uptime, cloud scale, or test coverage percentage is evidenced. Those values are UNKNOWN.

# 12. TECH STACK WITH ACTUAL USAGE

| Technology | Where Used | What For | Evidence | Depth |
|---|---|---|---|---|
| Next.js 16 / TypeScript | `app/`, `components/`, `lib/` | UI pages, 28 HTTP route handlers, worker orchestration bridge, history/file responses | `package.json`, `app/api/`, `lib/server/` | CORE |
| React 19 | `app/` | Studio, history, rules, settings, tools, license UI | `package.json`, `app/**/*.tsx` | CORE |
| Python | `worker/`, packaging | Workflow processing, state management, rules, licensing gate, installer build | `worker/*.py`, `packaging/` | CORE |
| FunASR | `worker/audio_translate/transcription/pipeline.py` | FSMN VAD, Paraformer Chinese ASR, punctuation | `worker/audio_translate/transcription/pipeline.py`, `requirements.txt` | CORE |
| llama.cpp (`llama-server`) / llama-cpp-python | `worker/audio_translate/translation/{hymt_translation,translation_server}.py` | Hy-MT2-1.8B Q8_0 GGUF Chinese-to-Vietnamese generation with shared slots | `worker/audio_translate/translation/`, `worker/requirements.txt`, `worker/tools/download_translation_*.py` | CORE |
| VieNeu TTS | `worker/audio_translate/tts/` | Vietnamese streaming TTS, worker pool, voice styles | `tts/adapters.py`, `tts/tts_runtime.py`, `.env.example` | CORE |
| yt-dlp | `worker/audio_translate/transcription/pipeline.py` | Audio-only YouTube download with retry settings | `worker/audio_translate/transcription/pipeline.py`, `requirements.txt` | SIGNIFICANT |
| FFmpeg / ffprobe | `worker/audio_translate/transcription/pipeline.py`, `manage.py` | Audio decoding, duration/probe/input validation | `worker/audio_translate/transcription/pipeline.py`, `worker/audio_translate/workflow/manage.py` | SIGNIFICANT |
| SQLite | `manage.py`, `postprocess.py` | Workflow registry and per-job segment checkpointing | `worker/audio_translate/workflow/manage.py`, `worker/audio_translate/workflow/postprocess.py` | SIGNIFICANT |
| JSON/JSONL + local filesystem | Worker/results/history | Job state, transcripts, manifests, artifact publication | `worker/audio_translate/core/storage.py`, `worker/audio_translate/workflow/results.py`, `lib/server/history.ts` | CORE |
| Windows DPAPI | shared SDK | Secure local license state | `shared-license-sdk/README.md`, `license_sdk/windows.py` | SIGNIFICANT |
| Ed25519 / cryptography | shared SDK | Signed machine-bound license verification | `shared-license-sdk/license_sdk/crypto.py` | SIGNIFICANT |
| WebSockets / Chrome DevTools Protocol | `worker/audio_translate/transcription/youtube_session.py` | Read dedicated profile cookies through local loopback browser debugging session | `worker/audio_translate/transcription/youtube_session.py`, `requirements.txt` | SUPPORTING |
| Rust | `security-core/` | License/Machine ID/DPAPI verification, worker command allowlist | `security-core/src/*.rs` | SIGNIFICANT |
| C# | `packaging/installer.cs` | Windows installer/bootstrap implementation | `audio-translates/packaging/installer.cs` | SUPPORTING |

# 13. ROLE EVIDENCE INDEX

## Backend Engineer Intern

HIGH:

- ARCH-01, ARCH-02, BE-01, BE-02, BE-03, DATA-01, DATA-02, SEC-01, SEC-02, SEC-03, CHALLENGE-02, CHALLENGE-03

MEDIUM:

- AI-02, AI-03, PLAT-01, PLAT-02, DEVOPS-01, CHALLENGE-01

## Platform / Cloud Engineer Intern

HIGH:

- None evidenced.

MEDIUM:

- ARCH-02, BE-02, BE-03, PLAT-01, PLAT-02, DEVOPS-01, DATA-02, SEC-01, SEC-02, SEC-03, CHALLENGE-02

## DevOps Engineer Intern

HIGH:

- DEVOPS-01

MEDIUM:

- ARCH-01, ARCH-02, BE-02, PLAT-01, PLAT-02, DATA-02, SEC-02, CHALLENGE-02

## AI Application Engineer Intern

HIGH:

- ARCH-02, AI-01, AI-02, AI-03, PLAT-02, CHALLENGE-01

MEDIUM:

- ARCH-01, BE-01, BE-02, PLAT-01, DEVOPS-01, DATA-01, DATA-02, CHALLENGE-02, CHALLENGE-03

## AI Backend Engineer Intern

HIGH:

- ARCH-02, BE-02, AI-01, AI-02, AI-03, DATA-01, DATA-02, CHALLENGE-01, CHALLENGE-02, CHALLENGE-03

MEDIUM:

- ARCH-01, BE-01, BE-03, PLAT-01, PLAT-02, DEVOPS-01, SEC-01, SEC-02, SEC-03

## Software Engineer Intern

HIGH:

- ARCH-01, ARCH-02, BE-01, BE-02, BE-03, AI-01, AI-02, AI-03, DATA-01, DATA-02, SEC-01, SEC-02, SEC-03, DEVOPS-01, CHALLENGE-01, CHALLENGE-02, CHALLENGE-03

MEDIUM:

- PLAT-01, PLAT-02

# 14. INFORMATION THAT REQUIRES USER CONFIRMATION

QUESTION-01:

Question: Which architecture, API, workflow, packaging, licensing, and AI integration decisions did you personally make or review versus generate/modify with an AI coding agent?

Why this matters for CV: Repository ownership does not establish personal contribution.

Related evidence: All ARCH, BE, PLAT, DEVOPS, AI, DATA, and SEC items.

QUESTION-02:

Question: Were the documented lint/build/unit/HTTP/smoke checks executed by you, on which commit/date, and with what retained logs?

Why this matters for CV: `IMPLEMENTATION_RESULT.md` reports outcomes, but this analysis only confirmed that code/scripts exist and did not independently rerun them.

Related evidence: DEVOPS-01; Section 9.

QUESTION-03:

Question: Installers 1.0.0–1.1.0 exist in `dist/`; has any been shipped, and has the app been used outside local development? If so, how many installations/users and in what environment?

Why this matters for CV: Repository provides packaging targets but does not prove deployment/adoption.

Related evidence: PLAT-01.

QUESTION-04:

Question: Beyond the speed/RAM numbers in section 11, what measured transcription quality, translation quality, TTS quality, processing latency, hardware configuration, and maximum audio duration have you tested?

Why this matters for CV: No benchmark/accuracy/throughput results are evidenced for this application.

Related evidence: AI-01, AI-02, AI-03; Section 11.

QUESTION-05:

Question: Why were filesystem state and a single-worker scheduler selected instead of a database-backed/distributed queue?

Why this matters for CV: Code establishes the choice and trade-offs, but not the decision context beyond local-persistent-service documentation.

Related evidence: ARCH-01, ARCH-02, DATA-01, DATA-02.

QUESTION-06:

Question: Did you create or materially modify the companion `admin-system` and `shared-license-sdk`, or are they provided/shared dependencies?

Why this matters for CV: Licensing/security evidence should only be attributed if your contribution is confirmed.

Related evidence: SEC-02, PLAT-01.
