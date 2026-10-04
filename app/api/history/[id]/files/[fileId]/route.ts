import { resolveHistoryFile } from "@/lib/server/history";
import { savedFileResponse } from "@/lib/server/file-response";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request, context: {params: Promise<{id: string; fileId: string}>}) {
  try {
    const {id, fileId} = await context.params;
    const saved = await resolveHistoryFile(id, fileId);
    return saved ? await savedFileResponse(request, saved.file) : Response.json({error: "File không tồn tại."}, {status: 404});
  } catch { return Response.json({error: "Không đọc được file đã lưu."}, {status: 404}); }
}
