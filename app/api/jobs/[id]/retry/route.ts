import { retryJob } from "@/lib/jobs";

export const runtime = "nodejs";

export async function POST(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const job = await retryJob(id);
  return job ? Response.json({ job }) : Response.json({ error: "Chỉ có thể retry job FAILED." }, { status: 409 });
}
