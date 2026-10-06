import { readFile } from "node:fs/promises";
import path from "node:path";
import { licenseCommand } from "@/lib/server/license";

// Keeps the short-lived lease fresh. The app asks the gateway for a new lease while the license is
// valid; the security service verifies and stores it. A lease is renewed once half of it has passed,
// so an app that is opened now and then never lapses. Only an app that stays offline past the lease
// plus the server-set grace stops accepting new work (viewing and downloading stay available).
export type LeaseOutcome = { lease: string; renewed: boolean; error?: string };
type Reply = Record<string, unknown> & { http_status: number; status?: string };

const RECHECK_MS = 10 * 60 * 1000;
const shared = globalThis as typeof globalThis & { audioLease?: { at: number; pending?: Promise<LeaseOutcome>; last?: LeaseOutcome } };
const state = shared.audioLease ?? (shared.audioLease = { at: 0 });

async function endpoint(): Promise<string | null> {
  try {
    const config = JSON.parse(await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ process.cwd(), "worker", "config", "genius.json"), "utf8"));
    const value = typeof config.endpoint === "string" ? config.endpoint : "";
    return value.startsWith("https://") || value.startsWith("http://127.0.0.1") ? value.replace(/\/$/, "") : null;
  } catch { return null; }
}

async function renew(): Promise<LeaseOutcome> {
  const status = (await licenseCommand({ action: "lease_status" })) as Reply;
  const phase = typeof status.lease === "string" ? status.lease : "UNKNOWN";
  if (status.http_status !== 200 || status.renew !== true) return { lease: phase, renewed: false };
  const base = await endpoint();
  if (!base) return { lease: phase, renewed: false, error: "GATEWAY_NOT_CONFIGURED" };
  const [credential, key] = (await Promise.all([licenseCommand({ action: "credential" }), licenseCommand({ action: "machine_pubkey" })])) as Reply[];
  if (credential.status !== "ACTIVE" || typeof credential.token !== "string" || typeof key.machine_pubkey !== "string") {
    return { lease: phase, renewed: false, error: String(credential.status ?? "INVALID") };
  }
  let response: Response;
  try {
    response = await fetch(`${base}/v1/lease`, {
      method: "POST", signal: AbortSignal.timeout(20000), cache: "no-store",
      headers: { "Content-Type": "application/json", Authorization: `License ${credential.token}`, "User-Agent": "audio-translate-app/1" },
      body: JSON.stringify({ machine_public: key.machine_pubkey }),
    });
  } catch { return { lease: phase, renewed: false, error: "GATEWAY_UNREACHABLE" }; } // Offline: the grace period covers this.
  const body = (await response.json().catch(() => ({}))) as { lease?: string; error?: string };
  if (response.status === 403 && body.error === "LICENSE_REVOKED") {
    await licenseCommand({ action: "lease_revoke" }); // Stop new processing now, not at expiry.
    return { lease: "REVOKED", renewed: false, error: "LICENSE_REVOKED" };
  }
  if (!response.ok || typeof body.lease !== "string") return { lease: phase, renewed: false, error: body.error ?? `HTTP_${response.status}` };
  const installed = (await licenseCommand({ action: "install_lease", token: body.lease })) as Reply;
  return installed.status === "OK" ? { lease: "VALID", renewed: true } : { lease: phase, renewed: false, error: String(installed.status ?? "INVALID") };
}

// Safe to call often: concurrent callers share one request and a fresh result is reused for ten minutes.
export function ensureLease(force = false): Promise<LeaseOutcome> {
  if (state.pending) return state.pending;
  if (!force && state.last && state.last.error === undefined && Date.now() - state.at < RECHECK_MS) return Promise.resolve(state.last);
  if (!force && state.last?.error && Date.now() - state.at < 60 * 1000) return Promise.resolve(state.last);
  state.pending = renew().catch((): LeaseOutcome => ({ lease: "UNKNOWN", renewed: false, error: "LEASE_CHECK_FAILED" }))
    .then((result) => { state.last = result; state.at = Date.now(); return result; })
    .finally(() => { state.pending = undefined; });
  return state.pending;
}
