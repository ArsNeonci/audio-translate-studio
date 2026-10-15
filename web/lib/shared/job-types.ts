// The shapes the local API returns (worker/audio_translate/api); the UI and the API agree on them through contracts/app-api.openapi.json.
import type { TranscriptionStep } from "@/lib/shared/transcription-progress";
export type Status = "QUEUED" | "DOWNLOADING" | "VAD" | "TRANSCRIBING" | "MERGING" | "TRANSCRIPTION_COMPLETED" | "TRANSLATING" | "TRANSLATION_COMPLETED" | "MODERATING" | "MODERATION_COMPLETED" | "TTS_GENERATING" | "SUBTITLE_BUILDING" | "VIDEO_MERGING" | "VIDEO_BURNING" | "COMPLETED" | "FAILED" | "CANCELLED" | "PAUSED" | "PARTIAL" | "DELETING" | "AWAITING_REVIEW";
export type Artifact = "source" | "zh" | "vi" | "moderated" | "voice" | "subtitle" | "video" | "video_subtitled";
export type Stage = "transcription" | "translation" | "moderation" | "tts" | "subtitle" | "video" | "burn";
export type Step = "DOWNLOAD" | "TRANSCRIPTION" | "TRANSLATION" | "MODERATION" | "TTS" | "SUBTITLE" | "VIDEO" | "BURN";
export const STEPS: Step[] = ["DOWNLOAD", "TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"];
/** The steps a run goes through (worker core/errors.py effective_steps): Subtitles for every workflow made since 3.1.0 and for tool 5,
 *  Video merge only when the run has videos, and Burn (the subtitled video) only when it was ticked. A run without the key never shows the step. */
export const runSteps = (job: {tool_steps?: Step[]; video?: {burn?: boolean} | unknown; subtitle?: unknown}): Step[] =>
  job.tool_steps || [...STEPS, ...(job.subtitle ? ["SUBTITLE" as const] : []), ...(job.video ? ["VIDEO" as const] : []), ...((job.video as {burn?: boolean} | undefined)?.burn ? ["BURN" as const] : [])];
export type VideoSettings = {files: import("@/components/video/video-picker").VideoClip[]; resolution: string; quality: string; burn?: boolean};
export type StepError = { step: Step; error_code: string; error_message: string; error_type: string; recoverable_manually: boolean; failed_at: string; retry_count: number };
export type StepState = { state: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED" | "PAUSED" | "SKIPPED"; progress?: number | null; started_at?: string | null; completed_at?: string | null; duration_ms?: number | null; retry_count: number; attempt: number; output_manifest?: {status:string}[]; error?: StepError };
export type Job = {
  id: string;
  url: string;
  name: string;
  status: Status;
  progress: number | null;
  workflow_no?: number;
  selected_voice_id?: string;
  selected_voice_style?: string;
  selected_address_profile?: string | null;
  translation_mode?: "genius";
  pause_reason?: string | null;
  tts_auto?: boolean;
  review_skipped?: boolean;
  tts_remote_progress?: {units_done:number;billed_chars:number};
  genius_progress?: {chunks_done:number;chunks_total:number;rows_done:number;rows_total:number;flagged_rows:number[];billed_chars:number};
  compute_device?: "cpu" | "gpu";
  storage_scope?: "workflows" | "tools";
  tool_steps?: Step[];
  started_at?: string | null;
  completed_at?: string | null;
  run_started_at?: string | null;
  total_duration_ms?: number | null;
  duration_ms: number;
  created_at: string;
  error: string | null;
  chunks_done?: number;
  chunks_total?: number;
  rows?: number;
  processed_ms?: number;
  workflow_version?: number;
  active_stage?: Stage | "download" | null;
  failed_stage?: Stage | "download" | null;
  stages?: Partial<Record<Stage, { percent: number | null; done?: number; total?: number | null }>>;
  artifacts?: Partial<Record<Artifact, boolean>>;
  steps?: Partial<Record<Step, StepState>>;
  video?: VideoSettings | null;
  subtitle?: {max_chars: number; min_seconds: number} | null;
  subtitle_voice?: {job_id: string};
  video_plan?: {mode: "copy" | "encode"; repeats: number | null; size_bytes: number | null};
  video_voice?: {job_id: string};
  transcription_steps?: TranscriptionStep[];
  asr_runtime?: {state:string;workers?:number;threads?:number;ram_available_gib?:number;required_available_gib?:number;thermal_available?:boolean;throttled?:boolean;tuning_deferred?:boolean;wait_started_at?:string;wait_timeout_seconds?:number;model_index?:number;model_total?:number;downloaded_gib?:number;total_gib?:number|null;file_index?:number;file_total?:number};
  translation_runtime?: {state:string;mode?:string;device?:string;slots?:number;allocated_slots?:number;threads?:number;n_batch?:number;available_gib?:number;required_available_gib?:number;required_vram_gib?:number;phase?:string;wait_seconds?:number;wait_timeout_seconds?:number;throttled?:boolean;start_free_gib?:number;extra_slot_gib?:number;reserve_gib?:number;cpu_target?:number;gpu_target?:number;temperature_limit?:number};
  memory_pause_reason?:string;
  auto_paused_for?:string|null;
  lane?: {workflows:number;target:number|null;units:number;stage:string|null;cores:number;yielding_for:number|null;waiting:boolean};
  translation_failures?: {row:number;part:number;start_ms:number;end_ms:number;source?:string;reason:string;failure_count:number;attempts:{seed:number;draft:string;reason:string}[]}[];
  translation_progress?: {done:number;total:number;exported_rows:number;buffered_rows:number};
  retry_step?: Step | null;
  pause_requested?: boolean;
  delete_requested?: boolean;
};

export type Scope = "workflows" | "tools";
export type HistoryFile = {id:string;step:string;type:string;path:string;size:number;created_at:string;status:"AVAILABLE"|"STALE"|"PUBLISHING"};
export type HistoryJob = Omit<Job,"status"> & {status:string;files:HistoryFile[];storage_scope:Scope;tool_type?:string;input_file?:string};

export type Rule = { id: string; source: string; replacement: string };
