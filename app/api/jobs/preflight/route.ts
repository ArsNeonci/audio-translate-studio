import { pythonCommand } from "@/lib/server/worker-client";
import {licenseDenial} from "@/lib/server/license";

export const runtime="nodejs";
export const dynamic="force-dynamic";

export async function GET(){
  const denied=await licenseDenial();if(denied)return denied;
  try{
    const {status,...body}=await pythonCommand<{status:number}>("manage.py",{action:"preflight"});
    return Response.json(body,{status,headers:{"Cache-Control":"no-store"}});
  }catch{return Response.json({error:"Không kiểm tra được tài nguyên."},{status:503});}
}
