export type BillingOpen = { ok: true; mode: "app" | "code" | "home" } | { ok: false; error: string };

// Asks the app server for the Billing portal address and opens it in a new tab. The server decides how (a one-time link while the
// licence is valid, the Customer Code otherwise); the browser never sees the licence token.
export async function openBillingPage(destination: "license" | "debt"): Promise<BillingOpen> {
  try {
    const response = await fetch("/api/billing", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ destination }) });
    const data = (await response.json()) as { url?: string; mode?: "app" | "code" | "home"; error?: string };
    if (!response.ok || !data.url) return { ok: false, error: data.error ?? "BILLING_UNAVAILABLE" };
    window.open(data.url, "_blank", "noopener");
    return { ok: true, mode: data.mode ?? "app" };
  } catch {
    return { ok: false, error: "BILLING_UNAVAILABLE" };
  }
}
