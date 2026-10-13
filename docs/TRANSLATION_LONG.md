# Translation: Hy-MT2-7B Q4_K_M

Backend: `hy-mt2-gguf`. Official model: https://huggingface.co/tencent/Hy-MT2-7B-GGUF
(replaced Hy-MT2-1.8B Q8_0 on 2026-10-05; accuracy over speed; the 1.8B files were deleted).

- File: `models/Hy-MT2-7B-Q4_K_M/Hy-MT2-7B-Q4_K_M.gguf`
- Revision: `ab8472660ac61fac25f1af43fac2599d52a8a775`
- Size: 4,624,648,896 bytes
- SHA-256: `9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b`
- Apache-2.0 license, model card and provenance remain alongside the weights.
- The official repo has only Q4_K_M, Q6_K and Q8_0: there is no official Q4_K_S/Q3_K_M fallback.

## RAM khi chạy (đo thật, 2026-10-05, máy 15,4 GiB, 8 lõi)

Đo bằng chênh lệch "In use" (tổng − khả dụng), không cộng từ danh sách tiến trình.

| Cấu hình `llama-server` | RAM tăng thêm | Ghi chú |
|---|---|---|
| Mặc định (repack Q4_K + mmap) | > 6,7 GiB | Phải dừng: RAM trống xuống dưới 0,8 GiB. Bản repack nằm cạnh trang mmap của GGUF |
| `--no-mmap` | — | Server thoát khi khởi động |
| **`--no-repack`** (đang dùng) | **4,52–4,77 GiB** (RSS 4,58, private 0,44) | Nạp 3 s; tốc độ như repack |
| Đường chạy thật, 2–3 slot | +5,28 GiB đỉnh | RAM trống thấp nhất 2,18 GiB |

- KV cache `q8_0`, ngữ cảnh 3072/slot: 0,32 GiB mỗi slot (f16 sẽ là 0,5 GiB).
- Ngưỡng: khởi động khi trống ≥ 6 GiB (`start_free_gib`), giữ ≥ 1 GiB cho hệ điều hành
  (`reserve_gib`), mỗi slot thêm 0,35 GiB (`extra_slot_gib`). Nếu chậm bất thường hoặc
  "In use" chạm trần: `HY_MT_CONTEXT_SIZE=2048`.
- Tốc độ: sinh ~6,0–6,7 token/s, đọc prompt ~31 token/s trên 8 luồng. Đường chạy thật 3,4 s/dòng
  (40 dòng, slot tự tăng lên 2, slot 3 bị gỡ vì không nhanh hơn).

## Mẫu chat theo từng model

Hy-MT2-7B dùng mẫu Hunyuan trong `tokenizer.chat_template` của GGUF:
`<|startoftext|>{nội dung}<|extra_0|>`, kết thúc `<|eos|>`. Mẫu `hy_*` của 1.8B chỉ là chữ thường
với 7B (model kết thúc ngay, 1 token). `hymt_translation.chat_format()` chọn mẫu theo metadata.

## Thử nghiệm cách dịch (dòng 101–160 của 000008)

| Cách | Khớp thẻ | Thời gian | Nhận xét |
|---|---|---|---|
| A. Nhóm câu ≤ 6 dòng + glossary (mặc định) | 19/19 | 5,5 s/dòng (1 slot) | Tên đúng, văn tự nhiên |
| B. Batch 20 dòng + 4 dòng ngữ cảnh + nhân vật/giới tính | 2/3 | tương đương A | Không dịch lạc sang ngữ cảnh; chất lượng ngang A, vài dòng sai khác |
| C. B + lượt 2 rà soát | 2/3 | 8,6 s/dòng | Lượt 2 gần như giữ nguyên bản nháp |

Download/verify: `.venv/Scripts/python.exe worker/tools/download_translation_model.py`.
Install runtime: `.venv/Scripts/python.exe worker/tools/download_translation_server.py`.
Only llama-server, runtime DLLs, CPU variants and licenses are retained.

The adapter uses the official Hy-MT2 chat tokens and Tencent's zh→xx template with a natural-style instruction. Background context is **not** sent (it made the 1.8B model translate the context instead of the source); glossary terms use the official terminology template. Three attempts change instruction/temperature/seed (natural 0.7 → conversational 0.3 → literal 0.0), top_p 0.6, top_k 20, repeat_penalty 1.05; rejected drafts are never fed back. Context is 4096 tokens, each source part at most 768 tokens; the output budget is `min(1536, 48 + 6 × source characters)`. Empty, runaway, multi-paragraph, label-leaking, control-token or Chinese-containing output is rejected. By default consecutive rows are translated per sentence with `<sN>` markers and split back to their timestamps (unaligned groups fall back to row prompts), and a per-job Hán-Việt name glossary (`working/name-glossary.json`) is sent as terminology. Details and measurements: `TRANSLATION_CHECKPOINTS.md`.

`HY_MT_*` settings are documented in `.env.example`. The live policy `worker/config/translation-runtime.json` controls fixed resource admission. Translation loads one slot and immediately translates real source rows: **no sample benchmark, warmup sweep, hardware speed test or calibration profile is used**, even if a legacy config still contains `calibrate=true`.

Default policy:

| Setting | Value | Meaning |
| --- | --- | --- |
| `start_free_gib` | 3.5 | Available RAM/commit required to try loading 1x |
| `extra_slot_gib` | 0.4 | Conservative RAM per extra shared-model slot |
| `reserve_gib` | 2 | RAM/commit reserve after model loading |
| `safety_gib` | 0.4 | Additional margin before expanding |
| `threads`, `threads_batch` | 4 | Shared server CPU budget, capped by physical cores |
| `n_batch` | 128 | Fixed batch setting, not benchmarked |
| `cpu_target`, `gpu_target` | 85 | Reduce load at this utilization; expand below 80% |
| `temperature_limit` | 85 | Stop admitting work at this temperature in Celsius |
| `observe_seconds` | 1 | Resource sampling interval |
| `scale_up_seconds` | 10 | Healthy resource period before adding one slot |
| `recovery_seconds` | 30 | Cooldown after pressure before restoring load |
| `vram_reserve_gib` | 0.5 | GPU memory reserve |
| `max_slots` | 0 | Automatic physical-core/resource ceiling |

The 3.5 GiB startup threshold permits a 1x attempt; it does not guarantee 2 GiB remains after loading. If even 1x cannot keep the reserve, the model is released and the workflow pauses with checkpoints preserved. Each expansion requires available RAM/commit of at least **2 GiB + additional slot allocations + 0.4 GiB safety**. The per-slot estimate is the larger of the configured 0.4 GiB and KV metadata estimate, so larger contexts cannot underbudget memory. At default context 4096, a new slot requires approximately 2.8 GiB available while the existing model is loaded.

The controller follows the resource admission pattern in Transcription 3/4: start real work, observe live resources, scale up after a healthy period, drain and shrink on pressure. It samples actual usage, not synthetic test translations. One llama-server shares model weights among slots. Resizing allocated KV slots restarts the helper only after active requests are saved. CPU/GPU overload reduces slots and CPU threads; thermal pressure stops admission and pauses after drain. Critical RAM/commit below 256 MiB releases the model immediately. Temperature sensors may be unavailable; telemetry reports whether a sensor exists. The reserve is a control target and other applications can briefly reduce it.

Each completed source row updates progress immediately, even inside the bounded read-ahead window and when rows finish out of order. The coordinator alone writes checkpoints and counts completed rows; final exports retain original order and timestamps. Parts within a row retain sequential context. The UI displays loading, memory waits, resource limits, parallel slot count and throttling. Policy edits apply at the next control check/drained boundary. No performance setting changes translation fingerprints. Already running Python processes keep their loaded code; the next start or Resume uses the updated controller.

Workflow device selection is frozen per job. GPU parallelism requires GPU-enabled llama-cpp-python and a CUDA-enabled llama-server via `HY_MT_SERVER_PATH`; the bundled helper is CPU-only. `--list-devices` checks backend availability without a benchmark. `engine=auto` retains single-slot embedded GPU execution if the helper cannot offload; `engine=server` reports an incompatible helper. GPU admission checks free VRAM separately. Startup estimates full model bytes + slot estimate + VRAM reserve + safety margin. NVIDIA utilization and temperature come from `nvidia-smi`; if GPU utilization cannot be read, automatic slot expansion is withheld. GPU controller tests use mocks on this CPU-only machine.

Old translation snapshots migrate at the next stage boundary, preserving glossary, TTS and device selection. Changed fingerprints prevent reuse of old-model translation parts. Paused jobs remain paused until Resume. Completed History is preserved; use Reprocess TRANSLATION to regenerate existing Vietnamese outputs.

Logs: `working/translation-server.log`. Telemetry: `working/translation-runtime.json`. Parts are checkpointed durably, in original row/timestamp order; pause drains active work. ASR and VieNeu-TTS remain separately configured.

Verification commands:

```powershell
.venv/Scripts/python.exe worker/dev/verify_runtime_tests.py
.venv/Scripts/python.exe worker/dev/verify_hymt_translation.py
.venv/Scripts/python.exe worker/dev/verify_translation_tokenizer.py --job <fixture-job-directory>
```

2026-10-04: 95 regression tests passed. Two Chinese samples translated with the real model in 8-9 seconds, including timestamp, export and resume checks. The trimmed runtime also passed real inference. Real tokenizer tests preserved all source characters across three samples of 3,200-3,800 characters. These are short CPU checks, not long-video or GPU benchmarks. Detailed reports are stored locally under `data/verification/`.


Resource-controller validation: 108 regression tests passed; TypeScript, localization/component rendering and targeted ESLint passed. Live workflow 000007 resumed with existing checkpoints under `mode=resource`, advanced beyond 160 completed rows and automatically reached three slots while available RAM stayed around 3.4 GiB. This checks real CPU inference with 4096-token contexts, without benchmark prompts. GPU thresholds have mocked test coverage; this machine has no usable GPU backend.
