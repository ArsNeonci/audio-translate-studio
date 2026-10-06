import { resolveHistoryFile } from "@/lib/server/history";
import { savedFileResponse } from "@/lib/server/file-response";
import { basicDenial } from "@/lib/server/edition";

const kinds: Record<string, string> = {zh: "ZH", vi: "VI", moderated: "MODERATED", voice: "VOICE"};
export async function artifactResponse(request: Request, id: string, kind: string) {
  if (!Object.hasOwn(kinds, kind)) return Response.json({error: "Unknown artifact"}, {status: 404});
  if (kind === "zh") {const denied = await basicDenial(); if (denied) return denied;}
  const params = new URL(request.url).searchParams;
  const extension = kind === "voice" ? "WAV" : params.get("format") === "jsonl" ? "JSONL" : "MD";
  try {
    const saved = await resolveHistoryFile(id, `${kinds[kind]}_${extension}`);
    if (!saved) return Response.json({error: "Output chưa sẵn sàng."}, {status: 404});
    const response = await savedFileResponse(request, saved.file, params.get("download") === "1");
    // Keep Studio's existing bounded plain-text preview contract.
    if (params.get("preview") === "1" && kind !== "voice" && response.ok) {
      const data = await response.json();
      return new Response(data.content+(data.next_offset != null ? "\n\n… Bản xem trước. Mở History để xem tiếp." : ""), {headers: {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}});
    }
    return response;
  } catch { return Response.json({error: "Không đọc được output đã lưu."}, {status: 503}); }
}
