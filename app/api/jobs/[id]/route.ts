import { getJob, schedule } from "@/lib/jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  await schedule();
  const job = await getJob(id);
  return job ? Response.json({ job }, { headers: { "Cache-Control": "no-store" } })
    : Response.json({ error: "Job không tồn tại." }, { status: 404 });
}
