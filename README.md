# Audio Studio — YouTube → Chinese → Vietnamese voice

Local Next.js Studio with a filesystem job queue and Python workers for FunASR, Hy-MT2-1.8B Q8_0 GGUF translation, replacement rules, and VieNeu-TTS. New jobs process in `data/tmp/<job_id>/` and persist final UTF-8 transcripts/Vietnamese audio in `RESULTS_ROOT/<job_id>/`; existing `data/jobs/` workspaces remain compatible.

## Saved results and History

Open **History** at `/history`, or **Open in History** from Studio Job Detail. Search by name/ID/source, choose newest/oldest and filter by status. Detail groups the existing files by step, with View/Download, audio playback and a paged JSON/JSONL viewer. Community Rules also has a menu entry at `/rules`.

`RESULTS_ROOT` defaults to `data/results/` (`AUDIO_DATA_DIR/results/` in an isolated environment). Set `RESULTS_ROOT=data/results` or another relative/absolute local folder in `.env.local` and restart. Relative values resolve from the project directory; no machine-specific absolute path is built into the code. Keep it separate from processing workspace directories.

```text
data/results/<job_id>/
  job.json, source.json, outputs.json
  transcription/transcript.zh.{jsonl,md}
  translation/transcript.vi.{jsonl,md}
  moderation/transcript.vi.moderated.{jsonl,md}, moderation-result.json
  tts/{voice.vi.wav,voice.manifest.jsonl}
data/tmp/<job_id>/                 # new jobs: processing inputs/checkpoints/temp
```

Each successful node publishes its validated files with a staged copy and atomic rename, then updates `outputs.json`. Staging is outside RESULTS_ROOT; for a different filesystem it uses a sibling `.audio-results-staging/` so replacement remains atomic. Completed results are never retry-cleanup targets. Abandoned `.tmp` files are cleaned; source/model inputs and reusable checkpoints are retained for recovery. Existing jobs in `data/jobs/` remain compatible and are backfilled into History without rerunning models or rewriting old job metadata. Published generations are preserved across startup backfill.

History uses only `job.json` and `outputs.json` indexes, a short cache of immediate job-directory names, and existence checks on listed files. It introduces no History database; the existing per-job SQLite inference checkpoint remains unchanged. File APIs accept a validated UUID and known file ID, enforce real-path containment (including symlinks), and expose only relative file paths.

API: `GET /api/history?search=...&status=COMPLETED&sort=newest&page=1`, `GET /api/history/<id>`, `GET /api/history/<id>/files/<fileId>?preview=1&offset=0`, `GET /api/history/<id>/files/<fileId>/download`. Preview reads at most 64 KiB per request and returns `next_offset`; complete downloads/audio are streamed with byte Range/206/416 support. Studio artifact APIs use the same persisted files, with no generated download copies.

History acceptance: `python worker/dev/verify_history_http.py --data data/verification/acceptance --pid <test-server-pid>` against the isolated server on port 3001. Restart that server, then use the same command with `--restart` instead of `--pid`. The script creates disposable large-file fixtures only under acceptance data.

## Translation, moderation, and Vietnamese voice

### Node errors and retry

Open **Chi tiết** for the five node states. A failed node offers **View Error**, **View Fix Guide** for recognized manual errors, and **Retry Step**. Fix the indicated dependency/path/config/cookie first, then retry. Commands in guides are displayed for you to run; the app does not execute them. Settings now offers **CPU / GPU** for TRANSCRIPTION 3/4, TRANSLATION and TTS. The choice is captured at workflow start and retained across retries; TRANSCRIPTION 4/4 merges text on CPU. See [Compute settings](docs/COMPUTE_SETTINGS.md) for backend requirements and the editable preference file. Translation/TTS model and batch settings remain in `working/adapters.json`; its device fields are derived from the workflow choice.

Retry executes only the failed node, then continues pending successors. Completed predecessors, valid chunk/WAV checkpoints and source inputs are preserved. Cleanup removes only the failed node's temporary/corrupt outputs. Errors persist in `job.json` and sanitized `errors.jsonl`; reloading the page retains the node state.

API: `GET /api/jobs/<id>/errors`, `GET /api/jobs/<id>/steps/<STEP>` (error + fix guide), `POST /api/jobs/<id>/steps/<STEP>` (retry, HTTP 202 or 409 for invalid state/lock). Step names are uppercase. Run `python -m unittest discover -s worker/tests -t worker -p "test_*.py" -v`; `worker/dev/verify_error_http.py --data data/verification/acceptance` verifies the isolated server on port 3001.

New jobs run the full workflow automatically. For an existing Chinese-only job, click **Tiếp tục dịch và đọc →**. Set up **Community Moderation Rules** before continuing if replacements are wanted. Job detail shows separate progress and View/Download controls for each transcript, plus Play/Download for the Vietnamese WAV.

Translation uses Tencent's `Hy-MT2-1.8B-Q8_0.gguf` offline with the local llama-server CPU runtime (embedded llama-cpp-python for GPU). Download with `.venv/Scripts/python.exe worker/tools/download_translation_model.py`; the script verifies the pinned size/SHA-256 and keeps only weights, model card, license and provenance in `models/Hy-MT2-1.8B-Q8_0/`. `HY_MT_MODEL_PATH` relocates the same model. No source clone or nested Git is needed. The adapter uses the official Hy-MT2 chat template and translation prompt, bounded source context and glossary. Old translation snapshots migrate at the next stage boundary; changed fingerprints prevent reuse of translations from the old model. Completed History remains available; use Reprocess TRANSLATION to regenerate existing Vietnamese outputs. See [translation setup](docs/TRANSLATION_LONG.md).

VieNeu source is detected at `../VieNeu-TTS-main/src`; override `VIENEU_SOURCE` if needed. Legacy nested provider paths remain compatible. VieNeu uses its unchanged `Vieneu(mode="v3turbo")` / `infer_stream` API and the Hải Đăng preset. CPU is the default. Hy-MT2 waits for 3.5 GiB free RAM before loading. The default is one slot with calibration disabled, avoiding benchmark-related pauses; memory protection and durable checkpoints remain active.

Install `worker/requirements.txt` in the project virtualenv. The adapters import the original VieNeu source without installing into or modifying that repo. VieNeu downloads its official v3 Turbo weights and required MOSS ONNX codec into `data/hf-cache/` on first use. These are dependencies of the selected VieNeu implementation. Each AI stage runs in a separate subprocess so its model memory is released before the next stage starts.

```text
TRANSCRIPTION_COMPLETED → TRANSLATING → TRANSLATION_COMPLETED
→ MODERATING → MODERATION_COMPLETED → TTS_GENERATING → COMPLETED
```

Outputs:

```text
data/jobs/<job_id>/
  transcript.zh.jsonl / transcript.zh.md
  transcript.vi.jsonl / transcript.vi.md
  transcript.vi.moderated.jsonl / transcript.vi.moderated.md
  moderation-result.json
  voice/000001.wav, 000002.wav, ...
  voice/voice.manifest.jsonl
  voice.vi.wav
  working/postprocess.sqlite3
  working/adapters.json
  working/replacement-rules.snapshot.json
```

`transcript.jsonl` remains a Chinese compatibility alias. The canonical new name is `transcript.zh.jsonl`; legacy jobs are migrated when continued. The three new stages stream JSONL, retain original segment timestamps/order, and commit per-segment checkpoints. Translation uses batches of at most 8 (default 4), losslessly splits long source text rather than truncating it, and refuses to commit an output that reaches its token limit without EOS. TTS only opens `transcript.vi.moderated.jsonl`. Completed segment WAVs are validated and reused. Final concatenation reads small PCM blocks in numeric manifest order. The WAV is continuous narration; source timestamps are metadata, not instructions to stretch/synchronize voice to the original video. WAV outputs above the RIFF 4 GB limit use RF64 with a `.wav` extension; some browser players may not play RF64, but downloading remains available.

Retry resumes the failed stage. Finished translation/moderation stages are skipped after a TTS failure. Model settings and the first rules snapshot are frozen per job; later rule edits apply to jobs that have not started moderation, including after a failed job resumes. Keep `working/` and `voice/` to preserve resumability.

### Replacement rules

Rules persist in `data/config/replacement-rules.json` as `{id, source, replacement}` records. Add, Edit, Delete are available in Studio and enforced through `/api/rules` and `/api/rules/<id>`. Original must be nonempty; empty replacement deletes the matched phrase. Text and rules are normalized to NFC. Matching is case-sensitive, literal substring matching (not regex): at each text position the longest matching phrase wins, and replacement output is not matched again. There is no implicit word-boundary or AI policy filter.

Moderation acquires the same OS file lock used by all CRUD operations, then takes its persistent rules snapshot. The lock remains held until success/failure status is published; API writes return HTTP 409 while locked. The OS releases it if the process crashes, so there is no stale lock-file cleanup race. The UI polls lock state every 3 seconds and disables Add/Edit/Delete/Save. Counts are stored in `moderation-result.json`, including per-rule replacements. The original Vietnamese file is never rewritten by moderation.

### Verification of the extended workflow

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s worker/tests -t worker -p "test_*.py" -v
npm run lint
npm run build
# Real model smoke test; keeps test rules/jobs isolated from the Studio data:
.\.venv\Scripts\python.exe worker/dev/smoke_e2e.py
```

For isolated HTTP/UI acceptance testing after the smoke test:

```powershell
$env:AUDIO_NEXT_DIST_DIR = '.next-verification'
$env:AUDIO_DATA_DIR = (Resolve-Path data/verification/acceptance).Path
npm run build
node node_modules/next/dist/bin/next start --port 3001
# In a second terminal at the project root:
.\.venv\Scripts\python.exe worker/dev/verify_http.py --data data/verification/acceptance
```

Use a fresh terminal (without these test environment overrides) for normal `npm run dev`. The production server must retain access to `worker/`, the virtualenv, model folders and writable `data/`; this is a local persistent service, not a serverless deployment.

## Run

Use Python 3.11 or 3.12, a compatible PyTorch installation, FFmpeg/ffprobe on `PATH`, and Node.js 22 or newer for Next.js and yt-dlp's YouTube support. The pinned Python packages come from the official yt-dlp and FunASR projects; the sibling source checkouts used during development are optional. Install `yt-dlp[default]` as listed in the requirements: its EJS package is needed for YouTube JavaScript challenges.

```powershell
cd <cloned-repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r worker/requirements.txt
npm install
$env:PYTHON_BIN = (Resolve-Path .\.venv\Scripts\python.exe).Path
npm run dev
```

Open <http://localhost:3000>. On Linux/macOS, activate `.venv/bin/activate` and set `PYTHON_BIN` to the virtualenv's `python` path. The first conversion downloads `paraformer-zh`, `fsmn-vad`, and `ct-punc` weights from ModelScope into `data/model-cache/`. Choose CPU/GPU in Settings; CPU is the default. Workflow device selection takes precedence over `FUNASR_DEVICE` and `VIENEU_DEVICE`.

yt-dlp uses the installed Node.js runtime for YouTube JavaScript challenges. If YouTube requires sign-in for your network, you may set `YTDLP_COOKIES_FILE` to a Netscape-format cookie file before starting the server; the app never reads browser cookies automatically.

The server automatically selects `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Linux/macOS when present. `PYTHON_BIN` overrides this selection. After moving the project between drives or machines, reinstall editable Python dependencies: their paths may still point to the old checkout. Check the imported package, not just `pip show`:

```powershell
.\.venv\Scripts\python.exe -c "import sys, yt_dlp; from yt_dlp.version import __version__; print(sys.executable); print(__version__); print(yt_dlp.__file__)"
.\.venv\Scripts\python.exe -m pip install --force-reinstall "yt-dlp[default]==2026.8.19"
```

## YouTube authentication

Open **Settings → Kết nối YouTube**. The app opens Edge (or Chrome) with its own profile;
sign into YouTube manually there, **close that dedicated browser window**, then click
**Kiểm tra kết nối**. Login uses the normal installed browser without remote debugging;
the app only reads the persisted session in a separate helper after login has finished.
If an old debug-enabled login window is open, close it and reopen from Settings. The
profile is retained; no browser security features, CAPTCHA or account checks are bypassed.
The app uses a temporary headless browser to refresh/read this profile on each new download.
Only `youtube.com` cookies are passed in memory to yt-dlp. Cookie values never enter API
responses, configuration files or installers. This does not guarantee permanent authentication:
YouTube can expire/revoke the session or request additional verification. The connection check
detects saved sign-in cookies; actual video access is checked when downloading.

The profile and connection settings live at `%LOCALAPPDATA%/AudioTranslate/youtube`, independent
of the installed version and workflow data. Upgrades/repackaging retain them on the same Windows
account. Each customer signs in on their own machine. Edge/Chrome must be installed and local
DevTools connections must be allowed by browser policy. The app never opens your regular browser
profile. Use `YOUTUBE_BROWSER_BIN` for a nonstandard browser executable or `YOUTUBE_SESSION_ROOT`
for an isolated storage directory. Do not point this directory at an existing personal profile.

A connected profile takes priority over the legacy `YTDLP_COOKIES_FILE`. **Ngừng sử dụng profile**
keeps the stored browser session but restores guest/file-cookie mode. Settings changes take effect
on the next download without restarting the server; completed audio and running AI stages are
untouched. If YouTube requests sign-in again, open **Đăng nhập lại / Mở YouTube**, complete the
verification, check the connection, and retry DOWNLOAD. Exporting a cookie file remains an optional
fallback described below.

If the log says `Sign in to confirm you're not a bot`, first confirm that the video plays in your browser on the same machine/network. If it does, supply YouTube cookies locally:

1. Export **only `youtube.com` cookies** in **Netscape cookies.txt** format using the [official yt-dlp cookie guide](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies). For Edge, use a cookie exporter compatible with Edge that supports this format. JSON exports do not work. The guide describes how to export from a private session so YouTube does not immediately rotate the cookies.
2. Save the file as `data/private/youtube-cookies.txt` (create the folder if needed). This directory is ignored by Git. Cookies provide access to your session: do not send their contents in chat or commit them.
3. Create `.env.local` in the project root, or add this line to the existing file:

   ```dotenv
   YTDLP_COOKIES_FILE=data/private/youtube-cookies.txt
   ```

4. Stop the server with Ctrl+C, run `npm run dev`, then click **Thử lại** on the failed job. Restarting is required after changing `.env.local`; replacing the cookie file at the same path only requires retrying the job.

If cookies are rejected, export a fresh file from a session that can play the video. An HTTP 429 response is a rate limit: wait before retrying and check your VPN/proxy or network. Cookies do not guarantee that YouTube will allow every request. Downloader warnings are retained in `data/jobs/<job_id>/working/worker.log`.

The Next.js process must run as a persistent local server with a writable `data/jobs/` directory. This MVP uses one Python worker at a time and filesystem state instead of a database. Do not deploy the API to a serverless runtime.

## Pipeline

1. yt-dlp selects `bestaudio` only, writes the stream as received, and resumes partial downloads.
2. FFmpeg decodes that source directly to a mono 16 kHz PCM pipe. It does not create a full decoded audio file or extract video.
3. FSMN-VAD consumes 200 ms PCM frames with a persistent streaming cache and writes global speech intervals to `working/vad.jsonl`.
4. Intervals are grouped at silence, capped near 30 seconds, and given 2.5 second overlap only where VAD had to split continuous speech. PCM processing keeps at most one chunk plus a six second overlap tail in memory.
5. FunASR's integrated `paraformer-zh` + `fsmn-vad` + `ct-punc` pipeline runs on each bounded chunk with `sentence_timestamp=True`. Sentence timestamps are shifted to the source timeline. Timestamp ownership removes overlapping output at forced boundaries.
6. Each completed chunk is stored atomically in `working/chunk-xxxxxx.json`. The merge writes canonical `transcript.jsonl` and `transcript.zh.md` atomically.

The worker restarts incomplete VAD passes, reuses downloaded source audio, skips completed ASR chunks, and rebuilds final outputs after a retry or server restart. `working/worker.log` and the job's `error` field explain failures. The Studio polls every three seconds and offers Retry for failed jobs.

## Licensing and universal Windows installer

The independent authority is `../admin-system`; reusable verification, machine fingerprint and secure storage live in `../shared-license-sdk`. Keep the Product repository at its existing path. For development, install the SDK into the Product environment with `.venv\Scripts\python.exe -m pip install ../shared-license-sdk`.

Admin registers `product.manifest.json` and builds `dist/AudioTranslate-1.1.0.exe` once per Product/version. This same installer goes to every customer. Runtime `licensing/public-config.json` contains Product ID/version and scheme metadata only. The Product root public key is compiled into the Windows Rust Security Core using the build-only `security-core/trust-anchor.json`. A successful release is immutable; adding customers, activation, renewal and delegated signing key rotation reuse it. Changes to shipped code require a new version.

After installation, open **License**, copy the Machine ID and send it to Admin. Admin creates the machine-bound token from a one-device entitlement; paste it as first activation. Import renewal tokens in sequence. Crypto verification and token import work offline. Start/retry processing needs trusted Internet time. Expired licenses retain access to app, history, file lists and downloads; preview, playback and new processing are blocked at API/worker boundaries.

The direct Windows bootstrap requires .NET Framework 4.5 or later (present on supported Windows 10/11 systems). The installer carries Node, Python, FFmpeg and the CPU inference dependencies. Model weights download when first needed and are cached in the runtime data directory. Its launch shortcut opens the localhost app; product results and DPAPI license state persist under the Windows user's `LocalAppData/AudioTranslate` directory.

Admin setup, activation, reset policy and verification commands are documented in `../admin-system/README.md`. Fully offline licensing cannot remotely revoke an already issued token or prevent a privileged attacker from patching the client or restoring all prior state.

### Security Phase 1 development

Run `.venv\Scripts\python.exe packaging/build_security_core.py` before starting Next.js. Install Rust (Windows MSVC with C++ Build Tools, or GNU with MinGW) for source builds; customers receive the compiled core and need no Rust installation. `Cargo.lock` pins dependencies. An absent/broken native core denies protected operations; there is no Python fallback or development unlock.

Next.js calls `security-core/bin/audio-security-core.exe` directly for license operations. It routes worker admission and execution through the same native broker. The broker accepts fixed commands, selects installation-relative Python/scripts, verifies the embedded trust chain and license before protected commands and workflow launch, and never accepts an arbitrary executable. Python `license_gate.py` is an additional native-call adapter. Editing that adapter alone cannot authorize a workflow through the unchanged backend/native broker.

The native core preserves existing Ed25519 tokens, renewal ordering, delegated key rotation, and the SHA-256 MachineGuid/SMBIOS UUID fingerprint. It reads legacy DPAPI state in place, then writes the native schema (`highest_sequence`, `key_version`, `last_verified_time`) atomically. Existing license state is not deleted by upgrades. Start/retry/reprocess/tools require the existing HTTPS time quorum; status and progress can be checked locally.

Layout abstraction is in `packaging/paths.py`: application/core binaries are install-relative, mutable data/results/history/preferences/logs are under LocalAppData, and the preferred future install location is Program Files/AudioTranslate. Phase 1 keeps the existing per-user installer. Relocation/service/ACL/signing changes are deferred. Re-register the updated manifest in Admin before building version 1.1.0; an already released 1.0.2 artifact remains immutable.

Tests: `.venv\Scripts\python.exe -m unittest discover -s packaging -p "test_security_phase1.py" -v` compiles an isolated synthetic-root core, checks real Windows DPAPI and machine compatibility, and launches the unchanged moderation workflow. It never changes production license state or Admin keys. `cargo test --locked --target <windows-target>` runs native unit tests. Physical cross-machine DPAPI validation still needs a second Windows host.

## Verify

```powershell
npm run lint
npm run build
python -m unittest discover -s worker/tests -t worker -p "test_*.py" -v
```

The tests cover yt-dlp's audio-only configuration, VAD chunk boundaries, PCM overlap, global ordering, duplicate suppression, and Chinese Unicode output. The full FunASR pipeline was also verified with the short Chinese WAV bundled in the supplied FunASR checkout. Live YouTube downloading depends on the network and YouTube access policy; a 429/sign-in challenge can require `YTDLP_COOKIES_FILE`.

## References

- [yt-dlp README, audio-only format and Python API](https://github.com/yt-dlp/yt-dlp#format-selection)
- [FunASR Python tutorial, VAD and sentence timestamps](https://github.com/modelscope/FunASR/blob/main/docs/tutorial/README.md)
- [FunASR Paraformer examples, streaming FSMN-VAD](https://github.com/modelscope/FunASR/blob/main/examples/industrial_data_pretraining/paraformer/README.md)
