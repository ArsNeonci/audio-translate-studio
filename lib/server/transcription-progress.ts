import type {Job, StepState} from '@/lib/server/jobs';

export type TranscriptionStep = StepState & {inferred?: boolean; memory_wait_run_ms?:number; memory_wait_ms?:number; wait_started_at?:string|null};
export function transcriptionView(job: Pick<Job, 'steps'|'transcription_steps'|'chunks_total'|'chunks_done'|'processed_ms'|'duration_ms'> & {status:string}, checkpoints: {vad?: string; chunks?: string} = {}): TranscriptionStep[] {
  if (job.transcription_steps?.length === 4) return job.transcription_steps;
  const parent = job.steps?.TRANSCRIPTION;
  const completed = parent?.state === 'COMPLETED';
  const current = completed ? 5 : job.status === 'MERGING' || job.status === 'TRANSCRIPTION_COMPLETED' ? 4
    : job.status === 'VAD' ? 1 : checkpoints.chunks || job.chunks_total ? 3 : checkpoints.vad ? 2 : 1;
  const active = parent?.state === 'RUNNING';
  const reliable = parent?.attempt === 1;
  const starts = reliable ? [parent?.started_at, checkpoints.vad, checkpoints.chunks, undefined] : [];
  const stopped = current === 3 && ['CANCELLED','PAUSED','FAILED'].includes(parent?.state || '') ? parent?.completed_at : undefined;
  const ends = reliable ? [checkpoints.vad, checkpoints.chunks, stopped, undefined] : [];
  return [1, 2, 3, 4].map(number => {
    const state: StepState['state'] = completed || number < current ? 'COMPLETED'
      : number === current && parent && parent.state !== 'PENDING' ? parent.state : 'PENDING';
    const progress = state === 'COMPLETED' ? 100 : state === 'PENDING' ? 0
      : number === 3 && job.chunks_total ? 100 * (job.chunks_done || 0) / job.chunks_total
      : number === 1 && job.status === 'VAD' && job.duration_ms ? 100 * (job.processed_ms || 0) / job.duration_ms : null;
    const start = starts[number - 1];
    const end = ends[number - 1];
    return {state, progress, retry_count: 0, attempt: 0, inferred: true,
      started_at: state === 'RUNNING' && active ? start : undefined,
      duration_ms: start && end ? Math.max(0, Date.parse(end) - Date.parse(start)) : null};
  });
}
