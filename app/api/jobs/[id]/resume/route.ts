import {managementResponse} from '@/lib/server/management';
export const runtime='nodejs';
export async function POST(request:Request,{params}:{params:Promise<{id:string}>}){
  return managementResponse(request,(await params).id,'resume');
}
