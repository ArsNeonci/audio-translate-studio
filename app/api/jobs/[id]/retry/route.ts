import { retryJob } from "@/lib/jobs";
import { licenseDenial } from "@/lib/license";

export const runtime = "nodejs";

export async function POST(_request: Request, context: { params: Promise<{ id: string }> }) {
  const denied = await licenseDenial(); if (denied) return denied;
  const { id } = await context.params;
  const job = await retryJob(id);
  return job ? Response.json({ job }) : Response.json({ error: "Chỉ có thể retry job lỗi hoặc tiếp tục job chỉ có bản chép tiếng Trung." }, { status: 409 });
}
