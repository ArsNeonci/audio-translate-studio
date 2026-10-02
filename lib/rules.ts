import { spawn } from "node:child_process";
import path from "node:path";
import { pythonBin, workerEnv } from "@/lib/python";
import {spawnSecurityCore} from "./security-core";

export type Rule = { id: string; source: string; replacement: string };
type RuleResponse = { status: number; rules?: Rule[]; locked?: boolean; error?: string };

export function rulesCommand(payload: Record<string, unknown>): Promise<RuleResponse> {
  return pythonCommand("rules.py", payload);
}

export function pythonCommand<T = RuleResponse>(script: "rules.py" | "retry.py" | "results.py" | "manage.py" | "youtube_session.py", payload: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    const brokered = script === "manage.py" || script === "retry.py";
    const child = brokered ? spawnSecurityCore({action:"command", script, payload}) : spawn(/*turbopackIgnore: true*/ pythonBin(), [path.join(/*turbopackIgnore: true*/ process.cwd(), "worker", script)],
      { cwd: process.cwd(), env: workerEnv(), stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    const timeout = setTimeout(() => { child.kill(); reject(new Error("Worker service timed out")); }, ["results.py", "manage.py"].includes(script) ? 300000 : script === "youtube_session.py" ? 60000 : 40000);
    child.stdout!.setEncoding("utf8");
    child.stdout!.on("data", (data: string) => { stdout += data; if (stdout.length > 16*1024*1024) { child.kill(); reject(new Error("Metadata response too large")); } });
    child.stderr!.resume();
    child.on("error", (error) => { clearTimeout(timeout); reject(error); });
    child.on("close", (code) => {
      clearTimeout(timeout);
      if (code !== 0) { reject(new Error("Rules service failed")); return; }
      try { resolve(JSON.parse(stdout)); } catch { reject(new Error("Invalid rules service response")); }
    });
    if (!brokered) { child.stdin!.on("error", () => {}); child.stdin!.end(JSON.stringify(payload)); }
  });
}

export async function rulesResponse(action: string, request?: Request, id?: string) {
  try {
    let payload: Record<string, unknown> = {};
    if (request && action !== "delete") {
      const text = await request.text();
      if (text.length > 24000) return Response.json({ error: "Rule quá dài." }, { status: 400 });
      try { payload = JSON.parse(text); } catch { return Response.json({ error: "JSON không hợp lệ." }, { status: 400 }); }
      if (!payload || Array.isArray(payload) || typeof payload !== "object") return Response.json({ error: "JSON object required." }, { status: 400 });
    }
    const { status, ...body } = await rulesCommand({ source: payload.source, replacement: payload.replacement, action, id });
    return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Không thể kết nối replacement rules service." }, { status: 500 });
  }
}
