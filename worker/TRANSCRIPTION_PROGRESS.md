# Four-row transcription telemetry

Display labels intentionally use only TRANSCRIPTION 1/4 through 4/4.
The four phases observe detection, safe segmentation, recognition, and timestamp
merge/final file validation. The existing recognition model still includes its
punctuation model; this change does not relocate inference or alter checkpoints.

New stage subprocesses record independent atomic telemetry in
working/transcription-progress.json. Timing accumulates over phase attempts;
cache reuse does not count as an execution. Reprocess from TRANSCRIPTION removes
the telemetry together with the associated checkpoints. Final history metadata
includes the four phase measurements. Overall retains the original five-stage
weighting rather than inflating transcription's share.

An already-running worker cannot pick up instrumentation without a restart.
getJob therefore derives a read-only view from its status, chunk counters and
checkpoint modification times. Legacy per-phase attempts remain unknown; timing
is shown only when checkpoint boundaries are available and the parent is on its
first attempt. No telemetry or job file is written by the observer.

The four-row component is integrated into Studio's Job Detail and History.
The temporary standalone progress page, observer component and API were removed
after consolidating the builds into the main Studio server.

Output counts are AVAILABLE published files only: download 0 (source internal),
phases 1–3 zero (checkpoints internal), phase 4 two, translation two, moderation
three, TTS two. An output becomes visible only after publication; completion of
phase 4 can briefly precede publication by its parent orchestrator.
