import {managementResponse} from "@/lib/server/management";
export const runtime="nodejs";
// Basic: continue (queue paid Voice generation) or finish without voice; body {"decision": "continue" | "finish"}.
export async function POST(request:Request,{params}:{params:Promise<{id:string}>}){return managementResponse(request,(await params).id,"review");}
