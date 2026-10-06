import {managementResponse} from "@/lib/server/management";
export const runtime="nodejs";
// Tool 4 on Basic: continue or finish a run held before Voice generation.
export async function POST(request:Request,{params}:{params:Promise<{id:string}>}){return managementResponse(request,(await params).id,"review","tools");}
