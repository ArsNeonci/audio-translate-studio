import {randomUUID} from "node:crypto";
import path from "node:path";
import {mkdir,open,unlink} from "node:fs/promises";
import {dataRoot} from "@/lib/server/python";
import { pythonCommand } from "@/lib/server/worker-client";
import {licenseDenial} from "@/lib/server/license";
import {schedule, validYoutubeUrl} from "@/lib/server/jobs";
import {historyList} from "@/lib/server/history";
import {isVoiceStyle} from "@/lib/shared/voice-styles";
import {isAddressProfile} from "@/lib/shared/address-profiles";
import {isTranslationMode} from "@/lib/shared/translation-modes";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(request:Request){await schedule();return Response.json(await historyList(new URL(request.url).searchParams,"tools"));}
export async function POST(request:Request){
  const denied=await licenseDenial();if(denied)return denied;
  if((request.headers.get("content-type")||"").startsWith("application/json")){
    // Tool 1 from a YouTube link: queued like a workflow, stops after Transcription.
    let tool:unknown,url:unknown;
    try{({tool,url}=await request.json());}catch{return Response.json({error:"Invalid JSON"},{status:400});}
    if(tool!=="transcription"||typeof url!=="string"||!validYoutubeUrl(url))return Response.json({error:"Enter a valid YouTube link"},{status:400});
    const {status,...body}=await pythonCommand<{status:number}>("manage.py",{action:"create",tool,url});
    if(status===200)void schedule();return Response.json(body,{status:status===200?201:status});
  }
  const params=new URL(request.url).searchParams,tool=params.get("tool"),name=params.get("name")||"";
  if(!["transcription","translation","moderation","tts"].includes(tool||"")||!name||name.length>255||/[\\/\x00]/.test(name))return Response.json({error:"Invalid tool or filename"},{status:400});
  const style=params.get("style")||undefined;if(style!==undefined&&!isVoiceStyle(style))return Response.json({error:"Invalid voice style"},{status:400});
  const mode=params.get("mode")||undefined;if(mode!==undefined&&(tool!=="translation"||!isTranslationMode(mode)))return Response.json({error:"Invalid translation mode"},{status:400});
  const address=mode==="genius"?undefined:params.get("address")||undefined;if(address!==undefined&&(tool!=="translation"||!isAddressProfile(address)))return Response.json({error:"Invalid address profile"},{status:400});
  const limit=tool==="transcription"?2*1024**3:64*1024**2;
  if(Number(request.headers.get("content-length"))>limit)return Response.json({error:"Upload too large"},{status:413});
  const root=path.join(/*turbopackIgnore: true*/ dataRoot,"uploads");await mkdir(/*turbopackIgnore: true*/ root,{recursive:true});
  const upload=path.join(/*turbopackIgnore: true*/ root,`${randomUUID()}.upload`),file=await open(/*turbopackIgnore: true*/ upload,"wx");let bytes=0;
  try{
    if(!request.body)throw new Error("Empty upload");
    const reader=request.body.getReader();
    try{while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>limit){await reader.cancel();return Response.json({error:"Upload too large"},{status:413});}let offset=0;while(offset<value.length){const written=await file.write(value,offset,value.length-offset);offset+=written.bytesWritten;}}}finally{reader.releaseLock();}
    await file.sync();await file.close();
    const {status,...body}=await pythonCommand<{status:number}>("manage.py",{action:"create",tool,upload,input_name:name,mime:request.headers.get("content-type")||"",voice:params.get("voice"),style,address,mode,auto:tool==="tts"&&params.get("auto")==="1"});
    if(status===200)void schedule();return Response.json(body,{status:status===200?201:status});
  }catch{return Response.json({error:"Cannot accept upload; check file and storage permissions."},{status:400});}
  finally{await file.close().catch(()=>{});await unlink(upload).catch(()=>{});}
}
