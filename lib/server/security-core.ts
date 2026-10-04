import path from "node:path";
import { spawn, type ChildProcess, type StdioOptions } from "node:child_process";
import { workerEnv } from "@/lib/server/python";

// Fixed installation-relative executable. No public-config/env verifier override.
export function securityCoreBin(): string {
  return path.join(/*turbopackIgnore: true*/ process.cwd(), "security-core", "bin", "audio-security-core.exe");
}
export function spawnSecurityCore(payload: Record<string, unknown>, output: StdioOptions = ["pipe", "pipe", "pipe"]): ChildProcess {
  const child = spawn(/*turbopackIgnore: true*/ securityCoreBin(), [], {
    cwd: process.cwd(), env: workerEnv(), stdio: output, windowsHide: true,
  });
  child.stdin?.on("error", () => {});
  child.stdin?.end(JSON.stringify(payload));
  return child;
}
