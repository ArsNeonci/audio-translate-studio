import path from "node:path";
import {randomUUID} from "node:crypto";
import {readFile, rename, unlink, writeFile} from "node:fs/promises";
import {jobDir} from "@/lib/server/jobs";
import {validCharacterSheet} from "@/lib/shared/address-profiles";
import {basicDenial} from "@/lib/server/edition";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// The sheet is drafted by the worker at Moderation and edited here; it takes
// effect on the next Reprocess from Moderation (moderation/address.py).
const editable = ["COMPLETED", "FAILED", "CANCELLED", "PAUSED", "PARTIAL"];
async function locate(id: string) {
  const dir = jobDir(id);
  if (!dir) return null;
  const job = await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ dir, "job.json"), "utf8").then(JSON.parse).catch(() => null) as {status?: string; storage_scope?: string} | null;
  return job && job.storage_scope !== "tools" ? {dir, job, file: path.join(/*turbopackIgnore: true*/ dir, "working", "characters.json")} : null;
}

export async function GET(_request: Request, {params}: {params: Promise<{id: string}>}) {
  // The sheet holds Chinese names and aliases.
  const denied = await basicDenial(); if (denied) return denied;
  const found = await locate((await params).id);
  if (!found) return Response.json({error: "Job không tồn tại."}, {status: 404});
  const sheet = await readFile(/*turbopackIgnore: true*/ found.file, "utf8").then(JSON.parse).catch(() => null);
  return Response.json({sheet: validCharacterSheet(sheet), editable: editable.includes(found.job.status || "")}, {headers: {"Cache-Control": "no-store"}});
}

export async function PUT(request: Request, {params}: {params: Promise<{id: string}>}) {
  const denied = await basicDenial(); if (denied) return denied;
  const found = await locate((await params).id);
  if (!found) return Response.json({error: "Job không tồn tại."}, {status: 404});
  if (!editable.includes(found.job.status || "")) return Response.json({error: "Pause or finish the current run first"}, {status: 409});
  const body = await request.text();
  if (body.length > 256 * 1024) return Response.json({error: "Request too large"}, {status: 413});
  let sheet;
  try { sheet = validCharacterSheet(JSON.parse(body)); } catch { sheet = null; }
  if (!sheet) return Response.json({error: "Invalid character sheet"}, {status: 400});
  const temp = `${found.file}.${randomUUID()}.tmp`;
  try { await writeFile(/*turbopackIgnore: true*/ temp, JSON.stringify(sheet, null, 2), "utf8"); await rename(/*turbopackIgnore: true*/ temp, found.file); }
  finally { await unlink(/*turbopackIgnore: true*/ temp).catch(() => {}); }
  return Response.json({sheet}, {headers: {"Cache-Control": "no-store"}});
}
