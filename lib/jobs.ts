import { spawn, type ChildProcess } from "node:child_process";
import { closeSync, existsSync, openSync } from "node:fs";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

export type Status = "QUEUED" | "DOWNLOADING" | "VAD" | "TRANSCRIBING" | "MERGING" | "COMPLETED" | "FAILED";
export type Job = {
  id: string;
  url: string;
  name: string;
  status: Status;
  progress: number;
  duration_ms: number;
  created_at: string;
  error: string | null;
  chunks_done?: number;
  chunks_total?: number;
  rows?: number;
  processed_ms?: number;
};

const root = path.join(process.cwd(), "data", "jobs");
const worker = path.join(process.cwd(), "worker", "pipeline.py");
const shared = globalThis as typeof globalThis & {
  audioStudioActive?: Map<string, ChildProcess>;
  audioStudioScheduling?: boolean;
};
const active = shared.audioStudioActive ?? (shared.audioStudioActive = new Map<string, ChildProcess>());

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
  return /^[0-9a-f-]{36}$/.test(id) ? path.join(root, id) : null;
}

export async function getJob(id: string): Promise<Job | null> {
  const dir = jobDir(id);
  if (!dir) return null;
  try { return JSON.parse(await readFile(path.join(dir, "job.json"), "utf8")) as Job; }
  catch { return null; }
}

export async function listJobs(): Promise<Job[]> {
  await mkdir(root, { recursive: true });
  const entries = await readdir(root, { withFileTypes: true });
  const jobs = await Promise.all(entries.filter((entry) => entry.isDirectory()).map((entry) => getJob(entry.name)));
  return jobs.filter((job): job is Job => job !== null).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

async function save(job: Job) {
  const dir = jobDir(job.id)!;
  const temp = path.join(dir, "job.json.tmp");
  await writeFile(temp, JSON.stringify(job, null, 2), "utf8");
  const { rename } = await import("node:fs/promises");
  await rename(temp, path.join(dir, "job.json"));
}

export async function createJob(url: string): Promise<Job> {
  const id = randomUUID();
  const job: Job = { id, url, name: new URL(url).searchParams.get("v") || "YouTube audio", status: "QUEUED",
    progress: 0, duration_ms: 0, created_at: new Date().toISOString(), error: null };
  await mkdir(path.join(root, id, "source"), { recursive: true });
  await mkdir(path.join(root, id, "working"), { recursive: true });
  await save(job);
  void schedule();
  return job;
}

export async function retryJob(id: string): Promise<Job | null> {
  const job = await getJob(id);
  if (!job || job.status !== "FAILED") return null;
  const next = { ...job, status: "QUEUED" as const, error: null };
  await save(next);
  void schedule();
  return next;
}

export async function schedule(): Promise<void> {
  if (shared.audioStudioScheduling || active.size) return;
  shared.audioStudioScheduling = true;
  try {
    const jobs = (await listJobs()).reverse();
    const next = jobs.find((job) => job.status !== "COMPLETED" && job.status !== "FAILED");
    if (!next || active.has(next.id)) return;
    const dir = jobDir(next.id)!;
    const logFd = openSync(path.join(dir, "working", "worker.log"), "a");
    const python = process.env.PYTHON_BIN || (process.platform === "win32" ? "python" : "python3");
    const modelCache = path.join(process.cwd(), "data", "model-cache");
    let child: ChildProcess;
    try {
      child = spawn(/*turbopackIgnore: true*/ python, [worker, dir], { cwd: process.cwd(), stdio: ["ignore", logFd, logFd], env: { ...process.env, MODELSCOPE_CACHE: process.env.MODELSCOPE_CACHE || modelCache } });
    } finally {
      closeSync(logFd);
    }
    active.set(next.id, child);
    child.on("error", async (error) => {
      const current = await getJob(next.id);
      if (current) await save({ ...current, status: "FAILED", error: `Không chạy được Python worker: ${error.message}` });
    });
    child.on("close", async (code) => {
      active.delete(next.id);
      const current = await getJob(next.id);
      if (code !== 0 && current && current.status !== "FAILED" && current.status !== "COMPLETED" && current.status !== "QUEUED") {
        await save({ ...current, status: "FAILED", error: `Worker dừng với exit code ${code}. Xem working/worker.log.` });
      }
      if (code === 0 && current && current.status !== "COMPLETED" && current.status !== "FAILED") {
        // An older worker still owns this job. Leave its status intact.
        return;
      }
      void schedule();
    });
  } finally { shared.audioStudioScheduling = false; }
}

export function outputExists(id: string): boolean {
  const dir = jobDir(id);
  return !!dir && existsSync(path.join(dir, "transcript.zh.md"));
}
