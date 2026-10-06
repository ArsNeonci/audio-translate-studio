import path from "node:path";
import net from "node:net";
import { readFileSync } from "node:fs";
import { spawn, type ChildProcess, type StdioOptions } from "node:child_process";
import { workerEnv } from "@/lib/server/python";

// Fixed installation-relative executable. No public-config/env verifier override.
export function securityCoreBin(): string {
  return path.join(/*turbopackIgnore: true*/ process.cwd(), "security-core", "bin", "audio-security-core.exe");
}

// The security service owns the pipe; its name carries the product id so Basic and Plus never
// share a channel. The id comes from the installed public config (a rendezvous label only).
let cachedProduct: string | undefined;
function pipePath(): string {
  if (cachedProduct === undefined) {
    try { cachedProduct = JSON.parse(readFileSync(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ process.cwd(), "licensing", "public-config.json"), "utf8")).product_id || "audio-translate"; }
    catch { cachedProduct = "audio-translate"; }
  }
  return `\\\\.\\pipe\\AudioTranslate.${cachedProduct}`;
}

// Query the service over the named pipe with 4-byte length framing (matches the Rust client).
export function callSecurityCore(payload: Record<string, unknown>, timeoutMs = 40000): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const body = Buffer.from(JSON.stringify(payload), "utf8");
    if (body.length > 65536) { reject(new Error("request too large")); return; }
    const header = Buffer.alloc(4); header.writeUInt32BE(body.length, 0);
    const socket = net.createConnection(/*turbopackIgnore: true*/ pipePath());
    const chunks: Buffer[] = []; let expected = -1; let settled = false;
    const finish = (fn: () => void) => { if (settled) return; settled = true; clearTimeout(timer); socket.destroy(); fn(); };
    const timer = setTimeout(() => finish(() => reject(new Error("security service timed out"))), timeoutMs);
    socket.on("connect", () => socket.write(Buffer.concat([header, body])));
    socket.on("data", (d) => {
      chunks.push(d); const buf = Buffer.concat(chunks);
      if (expected < 0 && buf.length >= 4) expected = buf.readUInt32BE(0);
      if (expected >= 0 && buf.length >= 4 + expected) {
        const json = buf.subarray(4, 4 + expected).toString("utf8");
        finish(() => { try { resolve(JSON.parse(json)); } catch (error) { reject(error); } });
      }
    });
    socket.on("error", (error) => finish(() => reject(error)));
    socket.on("end", () => finish(() => reject(new Error("security service closed"))));
  });
}
export function spawnSecurityCore(payload: Record<string, unknown>, output: StdioOptions = ["pipe", "pipe", "pipe"]): ChildProcess {
  const child = spawn(/*turbopackIgnore: true*/ securityCoreBin(), [], {
    cwd: process.cwd(), env: workerEnv(), stdio: output, windowsHide: true,
  });
  child.stdin?.on("error", () => {});
  child.stdin?.end(JSON.stringify(payload));
  return child;
}
