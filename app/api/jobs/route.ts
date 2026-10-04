import { listJobs, schedule, validYoutubeUrl } from "@/lib/server/jobs";
import { licenseDenial } from "@/lib/server/license";
import { pythonCommand } from "@/lib/server/worker-client";
import {ensureHistory} from "@/lib/server/history";
import {isVoiceStyle} from "@/lib/shared/voice-styles";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  await schedule();
  return Response.json({ jobs: await listJobs() }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  const denied = await licenseDenial(); if (denied) return denied;
  let url: unknown; let voice:unknown; let style:unknown; let queue_only:unknown;
  try { ({ url, voice, style, queue_only } = await request.json()); } catch { return Response.json({ error: "JSON không hợp lệ." }, { status: 400 }); }
  if (typeof url !== "string" || !validYoutubeUrl(url)) {
    return Response.json({ error: "Hãy nhập URL video YouTube hợp lệ (HTTPS)." }, { status: 400 });
  }
  if(voice!==undefined&&typeof voice!=="string")return Response.json({error:"Invalid voice"},{status:400});
  if(style!==undefined&&!isVoiceStyle(style))return Response.json({error:"Invalid voice style"},{status:400});
  if(queue_only!==undefined&&typeof queue_only!=="boolean")return Response.json({error:"Invalid queue option"},{status:400});
  try {
    await ensureHistory();
    const {status,...body}=await pythonCommand<{status:number;error?:string;job?:unknown}>("manage.py",{action:"convert",url,voice,style,queue_only:queue_only||false});
    if(status===200)void schedule();
    return Response.json(body,{status:status===200?201:status,headers:{"Cache-Control":"no-store"}});
  }catch{return Response.json({error:"Không kiểm tra được tài nguyên. Chưa tạo workflow; hãy thử lại."},{status:503});}
}
