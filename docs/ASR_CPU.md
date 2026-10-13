# CPU ASR Auto

CPU transcription is controlled by worker/audio_translate/transcription/asr_runtime.py. GPU selection keeps
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
RAM is below the configured startup threshold. Edit `worker/config/asr-memory.json`:

```json
{
  "start_free_gib": 4.5,
  "extra_worker_gib": 3.0,
  "max_workers": 0,
  "pressure_reserve_gib": 1.5
}
```

Before model loading, RAM capacity is
`0` below `start_free_gib`, otherwise
`1 + floor((available_GiB - start_free_gib) / extra_worker_gib)`.
Thus 4.5/7.5/10.5/13.5 GiB admit X1/X2/X3/X4, and the formula continues
on larger machines. `max_workers: 0` means automatic, capped by physical CPU
cores; set a positive integer to impose your own worker cap. The old
`ASR_MAX_WORKERS` environment variable is replaced by this JSON setting.
The file is reread during memory waits and runtime control (about every two
seconds); after this code update is loaded, editing JSON requires no restart.
Already paused jobs still need an explicit Resume.

During inference the memory budget credits `extra_worker_gib` per existing
worker, because its allocation is already deducted from available RAM. For
example, X1 with 4.5 GiB still free can expand to X2. CPU, commit, pressure,
scale-up delay and throughput checks remain active; capacity is not a promise
that all eligible workers are launched immediately. Observed model RSS no
longer raises the physical startup threshold (e.g. from 4.5 to 6.97 GiB).
Windows available RAM already includes reclaimable standby pages; never add
cache again. Windows commit headroom is checked separately, and pagefile capacity
is not counted as physical RAM. Pool expansion retains 1.5 GiB of system headroom,
by default (`pressure_reserve_gib`), distinct from the startup threshold.
Measured model allocation plus 25% is used for the separate commit check only.
These are application engineering thresholds, not Microsoft-recommended minima.
When only the single-worker budget fits, Auto defers calibration and starts
recognition with one worker capped at four physical-core threads. It does not
write a synthetic benchmark profile. A later invocation can calibrate when RAM
allows; valid existing profiles continue using measured memory peaks.
Memory admission waits at most ASR_MEMORY_WAIT_SECONDS (default 120), then pauses
while preserving checkpoints. Resume is explicit. Per-stage processing time
excludes new memory-admission waits; total workflow time still includes them.

An explicit standalone benchmark reads an already-downloaded/cancelled job:

    $env:PYTHONPATH="worker"; .venv/Scripts/python.exe -m audio_translate.transcription.asr_runtime --benchmark-job data/tmp/JOB_ID

It uses isolated cancellation controls; it does not resume that workflow.
Do not run it while other ASR workloads compete for the same CPU/RAM.

For an explicitly authorized X1/X2 memory trial, including the local app's
processes, use:

    .venv/Scripts/python.exe worker/dev/benchmark_asr_memory.py --job data/tmp/JOB_ID --workers 1 2 --allow-memory-trial

This diagnostic flag bypasses predicted memory admission only for the benchmark;
it does not lower production thresholds. Active workflows must first finish or
pause. Physical RAM below 256 MiB, commit headroom below 512 MiB, or the 300-second
trial timeout requests cancellation. The running inference may take time to drain.
The benchmark uses three complete source chunks (first/middle/last), warms every
worker, then times two rounds through the same recognition function as
Transcription 3/4. It preserves job checkpoints and the Auto profile. Reports and
raw samples under data/verification/asr-memory separate loading, warmup, inference,
and shutdown, and include the local app, coordinator, and model workers.
Use `--stagger-load` to load and warm workers sequentially before parallel timed
inference, matching the runtime's incremental pool startup. `--sample-source`
allows first/middle/last 30-second source windows (plus normal overlap) if no VAD
chunks exist; the report labels this different sampling basis. `--offline-license`
uses the existing native offline validation, retaining signature, machine,
expiration and local clock checks, when online trusted-time verification fails.
RSS sums can double-count shared pages; private bytes measure committed memory,
not just resident physical RAM. A small resident-RAM delta under paging pressure
alone is insufficient evidence for reducing worker admission requirements.

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

ASR_CPU_TARGET=85 and ASR_TEMP_LIMIT=85 are defaults.
RAM thresholds and maximum workers are in `worker/config/asr-memory.json`.
ASR_CPU_MODE=manual uses ASR_CPU_THREADS (fallback AI_NUM_THREADS) and
ASR_CPU_WORKERS; hardware admission still applies. Settings are process env
configuration, not changes to immutable released installers.

Studio displays Auto calibration, memory waiting and worker/thread state.
POST /api/jobs/ID/resume is explicit, license-gated and lock-protected. It only
admits CANCELLED or PAUSED workflows, removes their cancellation signal and queues the
cancelled stage while preserving all prior inputs, outputs and checkpoints.
This is not Reprocess. Implementation/build/testing never automatically resumes
the user's existing cancelled workflow.

## Convert preflight

Convert checks current CPU/RAM/power/available thermal sensors using the same
hardware and RAM reserve functions before allocating a job. No models are loaded
for this check. Physical admission uses the same configured base plus per-worker
increment. A valid recent Auto profile supplies the separate commit estimate;
without one the estimate is 2 GiB + 25%. Pool expansion is checked independently. Non-terminal queued/running
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
