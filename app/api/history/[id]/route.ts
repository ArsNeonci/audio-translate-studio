import { getHistoryJob } from "@/lib/server/history";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(_request: Request, context: {params: Promise<{id: string}>}) {
  try {
    const job = await getHistoryJob((await context.params).id);
    return Response.json(job ? {job} : {error: "Job không tồn tại."}, {status: job ? 200 : 404, headers: {"Cache-Control": "no-store"}});
  } catch { return Response.json({error: "Không đọc được History."}, {status: 503}); }
}

import {managementResponse} from "@/lib/server/management";
export async function DELETE(request:Request,{params}:{params:Promise<{id:string}>}){return managementResponse(request,(await params).id,"delete");}
