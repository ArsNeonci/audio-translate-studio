import { originAllowed } from "@/lib/server/origin";
import { quitApp, quitInfo } from "@/lib/server/app-control";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NO_STORE = { "Cache-Control": "no-store" };

export async function GET() {
  return Response.json(quitInfo(), { headers: NO_STORE });
}

// Stops the web server and every worker of this installation. With workflows running it needs {"force": true}.
export async function POST(request: Request) {
  if (!originAllowed(request)) return Response.json({ error: "Origin rejected" }, { status: 403 });
  const body = (await request.json().catch(() => ({}))) as { force?: boolean };
  return Response.json(quitApp(body.force === true), { headers: NO_STORE });
}
