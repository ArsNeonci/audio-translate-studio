import { originAllowed } from "@/lib/server/origin";
import { pythonCommand } from "@/lib/server/worker-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function localRequest(request: Request) {
  const url = new URL(request.url);
  return ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
    && originAllowed(request)
    && !["cross-site", "same-site"].includes(request.headers.get("sec-fetch-site") || "");
}

async function respond(action: string) {
  try {
    const { status, ...body } = await pythonCommand<{ status: number; error?: string }>("youtube_session.py", { action });
    return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Không thể kết nối dịch vụ YouTube. Kiểm tra Python worker." }, { status: 503 });
  }
}

export async function GET(request: Request) {
  if (!localRequest(request)) return Response.json({ error: "Local access required" }, { status: 403 });
  return respond("status");
}

export async function POST(request: Request) {
  if (!localRequest(request)) return Response.json({ error: "Origin rejected" }, { status: 403 });
  if (!request.headers.get("content-type")?.startsWith("application/json")) return Response.json({ error: "JSON required" }, { status: 415 });
  try {
    const text = await request.text();
    if (text.length > 1024) return Response.json({ error: "Request too large" }, { status: 400 });
    const payload = JSON.parse(text);
    if (!payload || !["open", "check", "disconnect", "close_browser"].includes(payload.action)) return Response.json({ error: "Invalid action" }, { status: 400 });
    return respond(payload.action);
  } catch {
    return Response.json({ error: "Invalid request" }, { status: 400 });
  }
}
