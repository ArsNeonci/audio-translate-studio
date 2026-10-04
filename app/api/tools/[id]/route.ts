import {getHistoryJob} from "@/lib/server/history";
import {managementResponse} from "@/lib/server/management";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(_request:Request,{params}:{params:Promise<{id:string}>}){const job=await getHistoryJob((await params).id,"tools");return Response.json(job?{job}:{error:"Tool run not found"},{status:job?200:404});}
export async function DELETE(request:Request,{params}:{params:Promise<{id:string}>}){return managementResponse(request,(await params).id,"delete","tools");}
