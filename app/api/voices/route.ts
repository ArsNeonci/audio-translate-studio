import {pythonCommand} from "@/lib/rules";
import {voiceSamples, previewBuilderStatus} from '@/lib/voice-previews';
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(){
  const {status,...body}=await pythonCommand<{status:number;voices?:{id:string;label:string;description:string}[]}>("manage.py",{action:"voices"});
  const samples=await voiceSamples();
  const voices=body.voices?.map(voice=>{const sample=samples.find(item=>item.id===voice.id);return {...voice,preview_url:sample?`/api/voices/preview/${sample.key}`:null};});
  return Response.json({...body,voices,preview_status:await previewBuilderStatus()},{status,headers:{"Cache-Control":"no-store"}});
}
