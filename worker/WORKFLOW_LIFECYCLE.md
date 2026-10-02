# Workflow controls

Completed workflow rows/details leave the main Studio on its next polling refresh
(up to 3 seconds). Published metadata, stage details and downloads remain in History;
this does not delete outputs or checkpoints. API enumeration still includes history
for Reprocess and scheduling compatibility.

Pause uses a cooperative signal with mode=pause. The UI continues showing the
running stage/elapsed with a persistent stopping status until worker acknowledgement.
ASR stops dispatching new segments, drains assigned segments to atomic checkpoints,
recounts committed IDs and enters PAUSED. A pause does not enforce the normal 120s
ASR task shutdown deadline; hung inference may need explicit abort. Translation's
current adapter batch and TTS's current text segment finish before the next outer
checkpoint/cancellation check. Moderation stops at row boundaries. Download keeps
resumable .part/.ytdl; unfinished VAD/merge/export work may restart from its last
durable boundary, not from arbitrary intermediate tensors or token positions.

Resume is lock/license gated, preserves valid chunk/SQLite/WAV checkpoints and
prior-stage outputs, and never automatically runs a FAILED stage. Failure remains
visible with an explicit "Chạy lại giai đoạn" action. After confirmation, fresh
retry deletes that stage's working outputs/caches and published files/manifest
entries; it retains source/predecessors, shared models/profiles and all other runs.
Only the failed node is retried; pending successors continue normally. Progress
is reset for that stage. Internal legacy retry without fresh=true retains valid
checkpoints for backwards-compatible automation.

Abort requires exact workflow number and scope on the server plus UI confirmation.
A durable delete-request marks the workflow as non-resumable/non-schedulable. A
running worker receives abort cancellation; deletion waits for its OS worker lock.
The scheduler/worker-close callback finalizes exact, validated workspace/published
result/upload targets. Requests survive server restart and are reconciled on the
next scheduling/polling pass. Model caches, Youtube profile, preview voices and
other workflows are never deletion targets. Deletion is permanent, not recycle-bin.

useNotice expires short action feedback after 3000 ms, cancels superseded timers
and cleans up on unmount. Workflow status, stopping/deletion flags, stage failure
details, progress, licence state and interactive resource-confirmation panels are
not transient notices and remain visible until state changes or dismissal.
