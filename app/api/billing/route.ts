import { billingInfo, openBilling } from "@/lib/server/billing-portal";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NO_STORE = { "Cache-Control": "no-store" };

export async function GET() {
  return Response.json(await billingInfo(), { headers: NO_STORE });
}

// Opens the Billing portal: returns the address to open in the browser. The customer never sees the licence token.
export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(request.url).origin) return Response.json({ error: "Origin rejected" }, { status: 403 });
  try {
    const data = (await request.json()) as { destination?: string };
    return Response.json(await openBilling(data.destination === "debt" ? "debt" : "license"), { headers: NO_STORE });
  } catch (error) {
    const code = error instanceof Error ? error.message : "BILLING_UNAVAILABLE";
    return Response.json({ error: /^[A-Z_0-9]{3,60}$/.test(code) ? code : "BILLING_UNAVAILABLE" }, { status: 502, headers: NO_STORE });
  }
}
