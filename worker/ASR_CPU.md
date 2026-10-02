# CPU ASR Auto

CPU transcription is controlled by worker/asr_runtime.py. GPU selection keeps
the existing serial implementation; GPU pool tuning is deliberately not added.

## Calibration and admission

Auto is the default (ASR_CPU_MODE=auto). It measures 4/6/8 threads, capped by
physical cores, sequentially with one model worker. Each configuration warms up
before two timed rounds over three representative complete segments. A CPU pool
of 2 workers × 3 threads is tested only on machines with at least 6 physical
cores and enough RAM. The pool must improve throughput by at least 10%, and all
calibration outputs must match baseline text and sentence boundaries within
30 ms. A warm-up result is never presented as a measured speedup.

CPU/model/package fingerprints invalidate the 7-day local profile in
data/config/asr-autotune.json. Calibration reads source audio, but never writes
workflow chunks or job state. On startup Auto waits before loading a model if
RAM cannot accommodate the model plus headroom. Initial estimate is 2 GiB;
after measurement it uses the worker's observed RSS/Windows peak working set
and 25% allocation margin. Reserve is max(3 GiB,20% total RAM). This is an
admission policy, not an OS memory allocation limit.

An explicit standalone benchmark reads an already-downloaded/cancelled job:

    .venv/Scripts/python.exe worker/asr_runtime.py --benchmark-job data/tmp/JOB_ID

It uses isolated cancellation controls; it does not resume that workflow.
Do not run it while other ASR workloads compete for the same CPU/RAM.

## Inference

One decoder producer streams PCM into a bounded queue (2 × max worker count).
Spawned processes each own one reusable model. Their only write target is the
assigned chunk-ID checkpoint, committed atomically. Model parameters, overlap
ownership, timestamps and punctuation remain the same as the original code.
Per-call ncpu is passed through FunASR 1.4.16's inference cfg, including VAD and
punctuation; no instance is shared between threads/processes.

One coordinator validates checkpoints, owns job/phase progress, and counts
completed IDs rather than the maximum index. Out-of-order results are merged
by the existing timestamp merge. Completed valid chunks are skipped on resume;
corrupt checkpoints are replaced only by successful recognition of that chunk.
The decoder currently scans past cached portions of compressed input, but does
not recognize them again. Random-access main decoding is not introduced.

Control samples CPU/RAM/power every 2 seconds. Pool expansion additionally needs
10 seconds of headroom and a measured single-worker throughput window; threads
are bounded by physical cores/worker count. CPU target is 85% on AC and 65% on
battery (soft targets, not hard process caps). RAM/CPU pressure retires extra
workers after their assigned chunk, reduces threads and may pause new work for
severe memory pressure or reported heat. A pool that does not improve measured
audio throughput over the single-worker window is disabled for that run.

Temperature monitoring depends on OS support. Windows often provides no sensor
through psutil; thermal_available=false is explicit telemetry. No promise of
temperature protection or a strict CPU percentage cap is made in that case.
Startup failures and worker crashes fail the stage without removing completed
chunks. Cancellation drains current recognition/checkpoint work up to a bounded
shutdown deadline before terminating an unresponsive process.

## Controls and resume

ASR_MAX_WORKERS=2, ASR_CPU_TARGET=85 and ASR_TEMP_LIMIT=85 are conservative
defaults. ASR_CPU_MODE=manual uses ASR_CPU_THREADS (fallback AI_NUM_THREADS) and
ASR_CPU_WORKERS; hardware admission still applies. Settings are process env
configuration, not changes to immutable released installers.

Studio displays Auto calibration, memory waiting and worker/thread state.
POST /api/jobs/ID/resume is explicit, license-gated and lock-protected. It only
admits CANCELLED workflows, removes their cancellation signal and queues the
cancelled stage while preserving all prior inputs, outputs and checkpoints.
This is not Reprocess. Implementation/build/testing never automatically resumes
the user's existing cancelled workflow.

## Convert preflight

Convert checks current CPU/RAM/power/available thermal sensors using the same
hardware and RAM reserve functions before allocating a job. No models are loaded
for this check. A valid recent Auto profile supplies observed peak memory; before
calibration the estimate is 2 GiB + 25% per workflow. A measured profile reserves
memory for its permitted worker count, not just one model. Non-terminal queued/running
workflow and tool jobs are counted, legacy IDs deduplicated, and queued/not-yet-
loaded model allocations are reserved. Existing ASR model memory is already
reflected in free RAM, so it is not reserved a second time. Future pipeline/TTS
peaks are not benchmarked; this remains a conservative ASR forecast, not a promise
that every stage fits or concurrent work is faster.

POST /api/jobs serializes check + creation with an OS lock across browser tabs.
Insufficient headroom returns RESOURCE_WARNING/409, with reasons and no workflow
number/checkpoint allocation. Studio offers explicit "Xếp hàng chờ" or "Để sau".
Queue confirmation reruns the check and only queues a job; it cannot override the
inference RAM wait or enable parallel workflow execution. The existing scheduler
still runs one workflow at a time. GET /api/jobs/preflight is read-only diagnostics
and does not schedule, load models, or create jobs. Snapshot conditions may change
after admission; the inference-time checks remain necessary.
