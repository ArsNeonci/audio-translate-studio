import { spawn } from "node:child_process";
import path from "node:path";
import { pythonBin, workerEnv } from "@/lib/server/python";
import { spawnSecurityCore } from "@/lib/server/security-core";

// Entry scripts live at worker/<script>; the native broker allowlist fixes their names.
export type WorkerScript = "rules.py" | "retry.py" | "results.py" | "manage.py" | "youtube_session.py" | "compute_settings.py" | "resources.py";

export function pythonCommand<T = unknown>(script: WorkerScript, payload: Record<string, unknown>): Promise<T> {
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
