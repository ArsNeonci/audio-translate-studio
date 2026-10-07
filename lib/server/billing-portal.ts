import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { licenseCommand } from "@/lib/server/license";
import { gatewayEndpoint } from "@/lib/server/lease";
import { dataRoot } from "@/lib/server/python";

// The Billing portal is a web page on the gateway where the customer pays service debt or buys a licence plan. Plans,
// prices and wording are set on the server, so none of that lives here. This module only:
//  - opens the portal (a one-time link made with the licence, or the Customer Code when the licence has expired), and
//  - collects the renewal tokens that were paid for there and installs them, so a paid renewal needs no copy and paste.
// The native core only releases the licence token while the licence is valid, so an expired licence cannot make a one-time
// link. The Customer Code, remembered from when it was valid, opens the portal with the code filled in instead; the customer
// pays there and copies the renewal token from the order page.
export type PortalLink = { url: string; mode: "app" | "code" };
export type BillingInfo = { code?: string; portal_url?: string; enabled: boolean };
type Reply = Record<string, unknown> & { http_status: number; status?: string };
type Gateway = { status: number; body: Record<string, unknown> };

const FILE = path.join(/*turbopackIgnore: true*/ dataRoot, "settings", "billing.json");
const FAST_MS = 15 * 60 * 1000, FAST_GAP_MS = 4000, SLOW_GAP_MS = 60 * 1000, CODE_REFRESH_MS = 24 * 3600 * 1000;
const shared = globalThis as typeof globalThis & { audioBilling?: { fastUntil: number; at: number; pending?: Promise<number>; checkedCode: number } };
const state = shared.audioBilling ?? (shared.audioBilling = { fastUntil: 0, at: 0, checkedCode: 0 });

async function remembered(): Promise<{ code?: string; portal_url?: string; saved_at?: number }> {
  try { return JSON.parse(await readFile(FILE, "utf8")); } catch { return {}; }
}
async function remember(code: string, portalUrl: string) {
  await mkdir(path.dirname(FILE), { recursive: true });
  const temp = `${FILE}.${process.pid}.tmp`;
  await writeFile(temp, JSON.stringify({ code, portal_url: portalUrl, saved_at: Date.now() }), "utf8");
  await rename(temp, FILE);
}
// The licence token, only while the licence is valid (the core refuses otherwise).
async function credential(): Promise<string | null> {
  const reply = (await licenseCommand({ action: "credential" })) as Reply;
  return reply.status === "ACTIVE" && typeof reply.token === "string" ? reply.token : null;
}
async function gateway(method: "GET" | "POST", route: string, token: string, body?: unknown): Promise<Gateway | null> {
  const base = await gatewayEndpoint();
  if (!base) return null;
  try {
    const response = await fetch(`${base}${route}`, {
      method, signal: AbortSignal.timeout(20000), cache: "no-store",
      headers: { "Content-Type": "application/json", Authorization: `License ${token}`, "User-Agent": "audio-translate-app/1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: response.status, body: (await response.json().catch(() => ({}))) as Record<string, unknown> };
  } catch { return null; } // offline
}

// What the licence page shows: the Customer Code and whether the portal can be opened at all.
export async function billingInfo(): Promise<BillingInfo> {
  let saved = await remembered();
  const stale = !saved.code || Date.now() - (saved.saved_at ?? 0) > CODE_REFRESH_MS;
  if (stale && Date.now() - state.checkedCode > 60 * 1000) {
    state.checkedCode = Date.now();
    const token = await credential();
    const reply = token ? await gateway("GET", "/v1/billing/code", token) : null;
    if (reply?.status === 200 && typeof reply.body.code === "string" && typeof reply.body.portal_url === "string" && reply.body.portal_url) {
      await remember(reply.body.code, reply.body.portal_url); saved = await remembered();
    }
  }
  return { code: saved.code, portal_url: saved.portal_url, enabled: !!(saved.code && saved.portal_url) || !!(await gatewayEndpoint()) };
}

// Opens the portal. With a valid licence: a one-time link that signs the customer in. Without one: the Customer Code, if remembered.
export async function openBilling(destination: "license" | "debt"): Promise<PortalLink> {
  state.fastUntil = Date.now() + FAST_MS; // from now on look for the paid renewal every few seconds
  const token = await credential();
  if (token) {
    const reply = await gateway("POST", "/v1/billing/session", token, { next: destination });
    if (reply?.status === 200 && typeof reply.body.url === "string") {
      if (typeof reply.body.customer_code === "string") void remember(reply.body.customer_code, new URL(reply.body.url).origin).catch(() => undefined);
      return { url: reply.body.url, mode: "app" };
    }
    if (reply && reply.status !== 200 && reply.status < 500) throw new Error(String(reply.body.error ?? `HTTP_${reply.status}`));
  }
  const saved = await remembered(); // expired licence, or the gateway could not be reached
  if (saved.code && saved.portal_url) return { url: `${saved.portal_url}/?code=${encodeURIComponent(saved.code)}`, mode: "code" };
  throw new Error(token ? "GATEWAY_UNREACHABLE" : "BILLING_CODE_UNKNOWN");
}

// Installs every renewal token the gateway holds for this licence, in order. Safe to call often: concurrent calls share one
// request, and it asks every few seconds only for 15 minutes after the portal was opened, otherwise once a minute.
export function fetchRenewals(force = false): Promise<number> {
  if (state.pending) return state.pending;
  const gap = Date.now() < state.fastUntil ? FAST_GAP_MS : SLOW_GAP_MS;
  if (!force && Date.now() - state.at < gap) return Promise.resolve(0);
  state.pending = collect().catch(() => 0).finally(() => { state.at = Date.now(); state.pending = undefined; });
  return state.pending;
}
async function collect(): Promise<number> {
  const token = await credential();
  if (!token) return 0; // an expired licence collects its token from the order page instead
  const status = (await licenseCommand({ action: "status" })) as Reply;
  const have = typeof status.sequence === "number" ? status.sequence : 0;
  const reply = await gateway("GET", `/v1/license/renewals?after=${have}`, token);
  const items = reply?.status === 200 && Array.isArray(reply.body.renewals) ? (reply.body.renewals as { sequence?: number; token?: string }[]) : [];
  let installed = 0;
  for (const item of [...items].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))) {
    if (typeof item.token !== "string") break;
    const result = (await licenseCommand({ action: "renew", token: item.token })) as Reply;
    if (result.status !== "ACTIVE") break; // the next one would be out of order
    installed += 1;
  }
  if (installed) void (await import("@/lib/server/lease")).ensureLease(true);
  return installed;
}
