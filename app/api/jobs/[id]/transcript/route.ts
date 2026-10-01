import { readFile } from "node:fs/promises";
import path from "node:path";
import { getJob, jobDir } from "@/lib/jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const job = await getJob(id);
  if (!job || job.status !== "COMPLETED") return Response.json({ error: "Transcript chưa sẵn sàng." }, { status: 404 });
  const content = await readFile(path.join(jobDir(id)!, "transcript.zh.md"));
  const download = new URL(request.url).searchParams.get("download") === "1";
  return new Response(content, { headers: {
    "Content-Type": "text/markdown; charset=utf-8",
    "Content-Disposition": `${download ? "attachment" : "inline"}; filename="transcript.zh.md"`,
    "Cache-Control": "no-store",
  } });
}
