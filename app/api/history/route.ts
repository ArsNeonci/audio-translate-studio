import { historyList } from "@/lib/history";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  try { return Response.json(await historyList(new URL(request.url).searchParams), {headers: {"Cache-Control": "no-store"}}); }
  catch { return Response.json({error: "Không đọc được History. Kiểm tra cấu hình và quyền lưu kết quả."}, {status: 503}); }
}
