import {resolveHistoryFile} from "@/lib/history";
import {savedFileResponse} from "@/lib/file-response";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(request:Request,{params}:{params:Promise<{id:string;fileId:string}>}){const {id,fileId}=await params;const resolved=await resolveHistoryFile(id,fileId,"tools");return resolved?savedFileResponse(request,resolved.file,new URL(request.url).searchParams.get("download")==="1"):Response.json({error:"Output unavailable or stale"},{status:404});}
