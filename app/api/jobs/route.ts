import { createJob, listJobs, schedule, validYoutubeUrl } from "@/lib/jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  await schedule();
  return Response.json({ jobs: await listJobs() }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  let url: unknown;
  try { ({ url } = await request.json()); } catch { return Response.json({ error: "JSON không hợp lệ." }, { status: 400 }); }
  if (typeof url !== "string" || !validYoutubeUrl(url)) {
    return Response.json({ error: "Hãy nhập URL video YouTube hợp lệ (HTTPS)." }, { status: 400 });
  }
  const job = await createJob(url);
  return Response.json({ job }, { status: 201 });
}
