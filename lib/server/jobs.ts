import { type ChildProcess } from "node:child_process";
import { closeSync, existsSync, openSync } from "node:fs";
import { appendFile, mkdir, readFile, readdir, writeFile, stat } from "node:fs/promises";
import {transcriptionView, type TranscriptionStep} from '@/lib/server/transcription-progress';
import path from "node:path";
import { randomUUID } from "node:crypto";
import { dataRoot, resultsRoot } from "@/lib/server/python";
import {spawnSecurityCore} from "@/lib/server/security-core";
import { pythonCommand } from "@/lib/server/worker-client";
import { licenseDenial } from "@/lib/server/license";

export type Status = "QUEUED" | "DOWNLOADING" | "VAD" | "TRANSCRIBING" | "MERGING" | "TRANSCRIPTION_COMPLETED" | "TRANSLATING" | "TRANSLATION_COMPLETED" | "MODERATING" | "MODERATION_COMPLETED" | "TTS_GENERATING" | "COMPLETED" | "FAILED" | "CANCELLED" | "PAUSED" | "PARTIAL" | "DELETING" | "AWAITING_REVIEW";
export type Artifact = "source" | "zh" | "vi" | "moderated" | "voice";
export type Stage = "transcription" | "translation" | "moderation" | "tts";
export type Step = "DOWNLOAD" | "TRANSCRIPTION" | "TRANSLATION" | "MODERATION" | "TTS";
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
  steps?: Record<Step, StepState>;
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

const root = path.join(/*turbopackIgnore: true*/ dataRoot, "tmp");
const legacyRoot = path.join(/*turbopackIgnore: true*/ dataRoot, "jobs");
const shared = globalThis as typeof globalThis & {
  audioStudioActive?: Map<string, ChildProcess>;
  audioStudioScheduling?: boolean;
  audioStudioRetry?: ReturnType<typeof setTimeout>;
};
const active = shared.audioStudioActive ?? (shared.audioStudioActive = new Map<string, ChildProcess>());
// How many workflows have a worker running right now (the Quit button warns before stopping them).
export function activeJobCount() { return active.size; }

export function validYoutubeUrl(value: string): boolean {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (url.protocol !== "https:" || url.username || url.password || url.port) return false;
    if (host === "youtu.be" || host === "www.youtu.be") return /^\/[\w-]{11}\/?$/.test(url.pathname);
    if (!["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"].includes(host)) return false;
    return (url.pathname === "/watch" && /^[\w-]{11}$/.test(url.searchParams.get("v") || ""))
      || /^\/(shorts|live)\/[\w-]{11}\/?$/.test(url.pathname);
  } catch { return false; }
}

export function jobDir(id: string): string | null {
  if (!/^[0-9a-f-]{36}$/.test(id)) return null;
  const tool = path.join(/*turbopackIgnore: true*/ dataRoot, "tool-tmp", id);
  if (existsSync(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ tool,"job.json"))) return tool;
  const current = path.join(/*turbopackIgnore: true*/ root, id);
  return !existsSync(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ current, "job.json")) && existsSync(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ legacyRoot, id, "job.json")) ? path.join(/*turbopackIgnore: true*/ legacyRoot, id) : current;
}

export async function getJob(id: string): Promise<Job | null> {
  const dir = jobDir(id);
  if (!dir) return null;
  try {
    const job = JSON.parse(await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ dir, "job.json"), "utf8")) as Job;
    const saved = job.workflow_no ? path.join(/*turbopackIgnore: true*/ resultsRoot,job.storage_scope||"workflows",String(job.workflow_no).padStart(6,"0")) : path.join(/*turbopackIgnore: true*/ resultsRoot,id);
    const manifest = JSON.parse(await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ saved,"outputs.json"),"utf8").catch(()=>'{"files":[]}')) as {files:{type:string;step:string;status:string}[]};
    const available=(type:string)=>manifest.files.some(f=>f.type===type&&f.status==="AVAILABLE");
    if(job.steps)for(const step of Object.keys(job.steps) as Step[])job.steps[step].output_manifest=manifest.files.filter(f=>f.step===step).map(f=>({status:f.status}));
    job.artifacts={source:available("SOURCE_AUDIO"),zh:available("ZH_MD"),vi:available("VI_MD"),moderated:available("MODERATED_MD"),voice:available("VOICE_WAV")};
    const working = path.join(/*turbopackIgnore: true*/ dir, 'working');
    job.delete_requested=existsSync(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working,'delete-request.json'));
    const stop=await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working,'cancel.signal'),'utf8').catch(()=>null);
    job.pause_requested=!!stop&&JSON.parse(stop).mode==='pause'&&job.status!=='PAUSED';
    const telemetry = await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, 'transcription-progress.json'), 'utf8').catch(()=>null);
    if (telemetry) job.transcription_steps = JSON.parse(telemetry).steps;
    const runtime = await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, 'asr-runtime.json'), 'utf8').catch(()=>null);
    if (runtime) job.asr_runtime = JSON.parse(runtime);
    const lane = await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, 'lane.json'), 'utf8').catch(()=>null);
    if (lane) job.lane = JSON.parse(lane);
    const translation = await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, 'translation-runtime.json'), 'utf8').catch(()=>null);
    if (translation) job.translation_runtime = JSON.parse(translation);
    const [translationErrors, translationProgress] = await Promise.all(['translation-errors.json', 'translation-progress.json'].map(name => readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, name), 'utf8').catch(()=>null)));
    if (translationErrors) job.translation_failures = JSON.parse(translationErrors).failures;
    if (translationProgress) job.translation_progress = JSON.parse(translationProgress);
    const genius = await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, 'genius-progress.json'), 'utf8').catch(()=>null);
    if (genius) job.genius_progress = JSON.parse(genius);
    const voice = await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, 'tts-remote-progress.json'), 'utf8').catch(()=>null);
    if (voice) job.tts_remote_progress = JSON.parse(voice);
    if (!job.transcription_steps?.length) {
      const [vad, chunks] = await Promise.all(['vad.done', 'chunks.json'].map(name => stat(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ working, name)).then(value=>value.mtime.toISOString()).catch(()=>undefined)));
      job.transcription_steps = transcriptionView(job, {vad, chunks});
    }
    return job;
  }
  catch { return null; }
}

export async function listJobs(includeTools=false): Promise<Job[]> {
  const {ensureHistory}=await import("./history"); await ensureHistory();
  await mkdir(/*turbopackIgnore: true*/ root, { recursive: true });
  const entries = await readdir(/*turbopackIgnore: true*/ root, { withFileTypes: true });
  const legacy = await readdir(/*turbopackIgnore: true*/ legacyRoot, { withFileTypes: true }).catch(() => []);
  const tools = includeTools ? await readdir(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ dataRoot,"tool-tmp"), {withFileTypes:true}).catch(()=>[]) : [];
  const ids = new Set([...entries, ...legacy, ...tools].filter(entry => entry.isDirectory()).map(entry => entry.name));
  const jobs = await Promise.all([...ids].map(getJob));
  return jobs.filter((job): job is Job => job !== null && (includeTools || job.storage_scope !== "tools")).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

async function save(job: Job) {
  const dir = jobDir(job.id)!;
  const temp = path.join(/*turbopackIgnore: true*/ dir, `job.${randomUUID()}.json.tmp`);
  const persisted = { ...job };
  delete persisted.artifacts;
  delete persisted.transcription_steps;
  delete persisted.asr_runtime;
  delete persisted.lane;
  delete persisted.translation_runtime;
  delete persisted.translation_failures;
  delete persisted.translation_progress;
  delete persisted.genius_progress;
  delete persisted.tts_remote_progress;
  delete persisted.pause_requested;
  delete persisted.delete_requested;
  await writeFile(temp, JSON.stringify(persisted, null, 2), "utf8");
  const { rename } = await import("node:fs/promises");
  await rename(temp, path.join(/*turbopackIgnore: true*/ dir, "job.json"));
}

export async function createJob(url:string,voice?:string):Promise<Job>{
  const {ensureHistory}=await import("./history");await ensureHistory();
  const result=await pythonCommand<{status:number;job:Job;error?:string}>("manage.py",{action:"create",url,voice});
  if(result.status!==200)throw new Error(result.error||"Cannot create workflow");
  void schedule();return result.job;
}

export async function retryJob(id: string): Promise<Job | null> {
  const job = await getJob(id);
  if (!job || (job.status !== "FAILED" && !(job.status === "COMPLETED" && job.workflow_version !== 2 && job.artifacts?.zh))) return null;
  if (job.status === "FAILED" && job.steps) {
    const step = (Object.keys(job.steps) as Step[]).find(key => job.steps?.[key].state === "FAILED");
    if (!step) return null;
    const result = await pythonCommand<{status: number}>("retry.py", { action: "retry", id, step, fresh:true });
    if (result.status !== 202) return null;
    void schedule();
    return getJob(id);
  }
  const next = { ...job, status: "QUEUED" as const, error: null };
  await save(next);
  void schedule();
  return next;
}

const TERMINAL = ["COMPLETED","FAILED","CANCELLED","PAUSED","PARTIAL","DELETING","AWAITING_REVIEW"];

// Re-evaluate admission while workflows wait, even when no page is polling.
function retryLater() {
  if (shared.audioStudioRetry) return;
  shared.audioStudioRetry = setTimeout(() => { shared.audioStudioRetry = undefined; void schedule(); }, 15000);
}

export async function schedule(): Promise<void> {
  if (shared.audioStudioScheduling) return;
  shared.audioStudioScheduling = true;
  try {
    const jobs = (await listJobs(true)).reverse();
    for(const job of jobs.filter(job=>job.delete_requested))await pythonCommand("manage.py",{action:"finish_abort",id:job.id});
    // Several workflows may run at once; the lane broker (worker/resources.py) decides
    // from free resources, oldest first, and resumes automatically paused workflows.
    const pending = jobs.filter((job) => !job.delete_requested&&!job.pause_requested&&!active.has(job.id)&&
      (!TERMINAL.includes(job.status)||(job.status==="PAUSED"&&!!job.auto_paused_for)));
    if (!pending.length) return;
    retryLater();
    if (await licenseDenial()) return;
    const decision = await pythonCommand<{status:number;start?:string|null;resumed?:string|null}>("resources.py",{action:"admit",ids:pending.map(job=>job.id),running:[...active.keys()]});
    if (decision.status!==200) return;
    if (decision.resumed) { setTimeout(()=>void schedule(), 500); return; }
    const next = pending.find(job=>job.id===decision.start);
    if (!next) return;
    const dir = jobDir(next.id)!;
    const logFd = openSync(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ dir, "working", "worker.log"), "a");
    let child: ChildProcess;
    try {
      child = spawnSecurityCore({action:"workflow",job_dir:dir}, ["pipe", logFd, logFd]);
    } finally {
      closeSync(logFd);
    }
    active.set(next.id, child);
    // Started one workflow; consider the next one shortly, after its lease registers.
    setTimeout(()=>void schedule(), 5000);
    let failure: Promise<void> | undefined;
    child.on("error", () => {
      failure = (async () => {
      const current = await getJob(next.id);
      if (current) await workerFailure(current, "PATH_MISSING", "Không chạy được Python worker. Kiểm tra PYTHON_BIN và .venv.");
      })().catch(() => { console.error("Cannot persist worker failure; check disk space and permissions."); });
    });
    child.on("close", (code) => { void (async () => {
      await failure;
      active.delete(next.id);
      const current = await getJob(next.id);
      if(current?.delete_requested){await pythonCommand("manage.py",{action:"finish_abort",id:next.id});void schedule();return;}
      if (code !== 0 && current && !["FAILED","COMPLETED","CANCELLED","PAUSED","DELETING","AWAITING_REVIEW"].includes(current.status)) {
        await workerFailure(current, "STEP_FAILED", `Worker dừng với exit code ${code}. Xem working/worker.log.`);
      }
      if (code === 0 && current && !["COMPLETED","FAILED","QUEUED","CANCELLED","PAUSED","PARTIAL","DELETING","AWAITING_REVIEW"].includes(current.status)) {
        // An older worker still owns this job. Leave its status intact.
        return;
      }
      void schedule();
    })().catch(() => { console.error("Cannot persist worker exit; check disk space and permissions."); }); });
  } catch {
    console.error("Cannot schedule worker; check data directory permissions and disk space.");
  } finally { shared.audioStudioScheduling = false; }
}

async function workerFailure(job: Job, code: string, message: string) {
  const step = job.retry_step || (job.active_stage?.toUpperCase() as Step) || job.tool_steps?.[0] || "DOWNLOAD";
  const steps = job.steps || Object.fromEntries(["DOWNLOAD", "TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"].map(key => [key, {state: "PENDING", attempt: 0, retry_count: 0}])) as Record<Step, StepState>;
  const item = steps[step];
  const error: StepError = {step, error_code: code, error_message: message, error_type: "WorkerProcessError", recoverable_manually: code === "PATH_MISSING", failed_at: new Date().toISOString(), retry_count: item.retry_count};
  item.state = "FAILED"; item.error = error;
  item.completed_at=error.failed_at;item.duration_ms=item.started_at?Math.max(0,Date.parse(error.failed_at)-Date.parse(item.started_at)):0;
  const total=(job.total_duration_ms||0)+(job.run_started_at?Math.max(0,Date.parse(error.failed_at)-Date.parse(job.run_started_at)):0);
  await save({...job, steps, status: "FAILED",completed_at:error.failed_at,run_started_at:null,total_duration_ms:total, active_stage: null, retry_step: null, failed_stage: step.toLowerCase() as Stage, error: message});
  await appendFile(path.join(/*turbopackIgnore: true*/ jobDir(job.id)!, "errors.jsonl"), JSON.stringify({...error, attempt: item.attempt || 1, timestamp: error.failed_at, message}) + "\n", "utf8");
}

export function outputExists(id: string): boolean {
  const dir = jobDir(id);
  // Basic keeps the working transcript encrypted (worker/audio_translate/core/sealing.py).
  return !!dir && ["transcript.zh.md", "transcript.zh.md.sealed"].some(name => existsSync(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ dir, name)));
}
