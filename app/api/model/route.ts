import { originAllowed } from "@/lib/server/origin";
import { modelState, startModelDownload } from "@/lib/server/model-download";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NO_STORE = { "Cache-Control": "no-store" };

export async function GET() {
  return Response.json(await modelState(), { headers: NO_STORE });
}

// Starts (or resumes) the download of the offline translation model. It runs in this server process; the page polls GET.
export async function POST(request: Request) {
  if (!originAllowed(request)) return Response.json({ error: "Origin rejected" }, { status: 403 });
  return Response.json(await startModelDownload(), { headers: NO_STORE });
}
