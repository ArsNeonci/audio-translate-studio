import { pythonCommand } from "@/lib/server/worker-client";
import {licenseDenial} from "@/lib/server/license";
import {schedule} from "@/lib/server/jobs";
import {basicDenial} from "@/lib/server/edition";
import {isTranslationMode} from "@/lib/shared/translation-modes";
export async function managementResponse(request:Request,id:string,action:string,scope="workflows"){
  if(action==="reprocess"||action==="resume"||action==="review"){const denied=await licenseDenial();if(denied)return denied;}
  let payload:Record<string,unknown>={};
  if(action!=="cancel"&&action!=="pause"&&action!=="resume"){
    const body=await request.text();if(body.length>4096)return Response.json({error:"Request too large"},{status:413});
    try{payload=JSON.parse(body);}catch{return Response.json({error:"Invalid JSON"},{status:400});}
  }
  if(action==="reprocess"&&(payload.step==="DOWNLOAD"||payload.step==="TRANSCRIPTION")){const basic=await basicDenial();if(basic)return basic;}
  if(action==="reprocess"&&payload.mode!==undefined&&!isTranslationMode(payload.mode))return Response.json({error:"Invalid translation mode"},{status:400});
  const {status,...body}=await pythonCommand<{status:number;error?:string}>("manage.py",{...payload,action,id,scope});
  if(status===200&&(action==="reprocess"||action==="resume"||action==="review"))void schedule();
  return Response.json(body,{status,headers:{"Cache-Control":"no-store"}});
}
