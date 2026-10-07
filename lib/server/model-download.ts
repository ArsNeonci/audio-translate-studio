import { createHash } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import { mkdir, rename, stat, unlink, writeFile, readFile } from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { licenseCommand } from "@/lib/server/license";
import { gatewayEndpoint } from "@/lib/server/lease";

// The offline translation model (4.6 GB) is not inside the installer: Windows refuses executables over 4 GiB. After activation the
// app asks the gateway for a one-hour signed link (valid licence only), downloads the file here, and keeps it only if its size and
// SHA-256 equal the values pinned below. A file that fails the check is deleted, so a wrong or tampered download is never loaded.
export const MODEL = {
  id: "hy-mt2-7b-q4km",
  file: "Hy-MT2-7B-Q4_K_M.gguf",
  size: 4624648896,
  sha256: "9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b",
};
// rate (bytes/s) and eta (seconds) exist while downloading; license is the licence status, so the page can say "activate first" instead of failing.
export type ModelState = { phase: "ready" | "missing" | "downloading" | "verifying" | "error"; done: number; total: number; error?: string; rate?: number; eta?: number; license?: string };

// The launcher sets HY_MT_MODEL_PATH to the per-user data folder; a development checkout keeps its own models folder.
export const modelPath = () => process.env.HY_MT_MODEL_PATH || path.join(/*turbopackIgnore: true*/ process.cwd(), "models", "Hy-MT2-7B-Q4_K_M", MODEL.file);
const shared = globalThis as typeof globalThis & { audioModel?: { run?: Promise<void>; state: ModelState; meter?: { at: number; from: number } } };
const holder = shared.audioModel ?? (shared.audioModel = { state: { phase: "missing", done: 0, total: MODEL.size } });
const RETRIES = 6;

class DownloadError extends Error {}
const fail = (code: string) => new DownloadError(code);

// "ready" needs a marker written after the hash was checked, so a start-up does not re-hash 4.6 GB every time.
async function verifiedMarker(file: string) {
  try {
    const [info, marker] = await Promise.all([stat(file), readFile(`${file}.ok`, "utf8").then(JSON.parse)]);
    return info.size === MODEL.size && marker.size === info.size && marker.mtimeMs === Math.trunc(info.mtimeMs) && marker.sha256 === MODEL.sha256;
  } catch { return false; }
}

async function licenseStatus(): Promise<string> {
  try { return String(((await licenseCommand({ action: "status" })) as { status?: string }).status ?? "UNKNOWN"); } catch { return "UNKNOWN"; }
}

export async function modelState(): Promise<ModelState> {
  if (holder.run) return holder.state;
  if (await verifiedMarker(modelPath())) return { phase: "ready", done: MODEL.size, total: MODEL.size };
  const base = holder.state.phase === "error" ? holder.state : { phase: "missing" as const, done: 0, total: MODEL.size };
  return { ...base, license: await licenseStatus() };
}

async function link(): Promise<string> {
  const reply = (await licenseCommand({ action: "credential" })) as { status?: string; token?: string };
  if (reply.status !== "ACTIVE" || !reply.token) throw fail("LICENSE_REQUIRED");
  const base = await gatewayEndpoint();
  if (!base) throw fail("GATEWAY_NOT_CONFIGURED");
  let response: Response;
  try {
    response = await fetch(`${base}/v1/model/url`, { method: "POST", signal: AbortSignal.timeout(20000), cache: "no-store",
      headers: { "Content-Type": "application/json", Authorization: `License ${reply.token}`, "User-Agent": "audio-translate-app/1" }, body: JSON.stringify({ model: MODEL.id }) });
  } catch { throw fail("OFFLINE"); }
  const body = (await response.json().catch(() => ({}))) as { url?: string; error?: string };
  if (!response.ok || !body.url) throw fail(/^[A-Z_]{3,40}$/.test(body.error ?? "") ? body.error! : `HTTP_${response.status}`);
  return body.url;
}

async function sha256(file: string, report: (bytes: number) => void): Promise<string> {
  const hash = createHash("sha256"); let seen = 0;
  for await (const chunk of createReadStream(file, { highWaterMark: 4 * 1024 * 1024 })) { hash.update(chunk as Buffer); seen += (chunk as Buffer).length; report(seen); }
  return hash.digest("hex");
}

async function run(): Promise<void> {
  const target = modelPath(), partial = `${target}.part`;
  await mkdir(path.dirname(target), { recursive: true });
  // A complete file that has no marker yet (a development checkout, or a copy placed by hand) is hashed, not downloaded again.
  if ((await stat(target).then((info) => info.size, () => 0)) === MODEL.size) {
    holder.state = { phase: "verifying", done: 0, total: MODEL.size };
    if ((await sha256(target, (bytes) => { holder.state = { phase: "verifying", done: bytes, total: MODEL.size }; })) !== MODEL.sha256) throw fail("CHECKSUM_MISMATCH");
    const info = await stat(target);
    await writeFile(`${target}.ok`, JSON.stringify({ size: info.size, mtimeMs: Math.trunc(info.mtimeMs), sha256: MODEL.sha256 }), "utf8");
    return;
  }
  const size = async () => stat(partial).then((info) => info.size, () => 0);
  let url = "";
  for (let attempt = 0; attempt < RETRIES; attempt++) {
    let offset = await size();
    if (offset === MODEL.size) break;
    if (offset > MODEL.size) { await unlink(partial); offset = 0; }
    holder.state = { phase: "downloading", done: offset, total: MODEL.size };
    try {
      if (!url) url = await link();
      const response = await fetch(url, { headers: offset ? { Range: `bytes=${offset}-` } : {}, cache: "no-store" });
      if (response.status === 403 || response.status === 401) { url = ""; throw fail("LINK_EXPIRED"); }
      if (offset && response.status !== 206) { await unlink(partial).catch(() => {}); throw fail("RESUME_REFUSED"); }
      if (!response.ok || !response.body) throw fail(`HTTP_${response.status}`);
      const out = createWriteStream(partial, { flags: offset ? "a" : "w" });
      let done = offset;
      const body = Readable.fromWeb(response.body as never);
      holder.meter = { at: Date.now(), from: offset };
      body.on("data", (chunk: Buffer) => {
        done += chunk.length;
        const seconds = (Date.now() - holder.meter!.at) / 1000;
        const rate = seconds >= 1 ? (done - holder.meter!.from) / seconds : undefined;
        holder.state = { phase: "downloading", done, total: MODEL.size, rate, eta: rate ? Math.ceil((MODEL.size - done) / rate) : undefined };
      });
      await pipeline(body, out);
    } catch (error) {
      if (error instanceof DownloadError && ["LICENSE_REQUIRED", "GATEWAY_NOT_CONFIGURED", "MODEL_LINK_LIMIT", "MODEL_DOWNLOAD_DISABLED", "LICENSE_REVOKED", "EXPIRED"].includes(error.message)) throw error;
      if (attempt === RETRIES - 1) throw error instanceof DownloadError ? error : fail("OFFLINE");
      await new Promise((resolve) => setTimeout(resolve, 3000 * (attempt + 1)));
    }
  }
  if ((await size()) !== MODEL.size) throw fail("INCOMPLETE");
  holder.state = { phase: "verifying", done: 0, total: MODEL.size };
  const actual = await sha256(partial, (bytes) => { holder.state = { phase: "verifying", done: bytes, total: MODEL.size }; });
  if (actual !== MODEL.sha256) { await unlink(partial).catch(() => {}); throw fail("CHECKSUM_MISMATCH"); }
  await rename(partial, target);
  const info = await stat(target);
  await writeFile(`${target}.ok`, JSON.stringify({ size: info.size, mtimeMs: Math.trunc(info.mtimeMs), sha256: MODEL.sha256 }), "utf8");
}

// One download at a time; calling again while it runs just reports it.
// The check and the claim happen in the same synchronous step (nothing is awaited before holder.run is set), so two clicks that
// arrive together can never start two downloads, and a repeated request neither asks the gateway for another link nor uses up
// the daily link allowance.
export async function startModelDownload(): Promise<ModelState> {
  if (holder.run) return holder.state;
  const present = verifiedMarker(modelPath());
  holder.state = { phase: "downloading", done: 0, total: MODEL.size };
  holder.run = (async () => { if (!(await present)) await run(); })()
    .then(() => { holder.state = { phase: "ready", done: MODEL.size, total: MODEL.size }; })
    .catch((error) => { holder.state = { phase: "error", done: 0, total: MODEL.size, error: error instanceof DownloadError ? error.message : "MODEL_DOWNLOAD_FAILED" }; })
    .finally(() => { holder.run = undefined; });
  return (await present) ? { phase: "ready", done: MODEL.size, total: MODEL.size } : holder.state;
}
