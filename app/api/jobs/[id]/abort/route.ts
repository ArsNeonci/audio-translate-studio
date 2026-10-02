import {managementResponse} from '@/lib/management';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function POST(request:Request,context:{params:Promise<{id:string}>}){
  return managementResponse(request,(await context.params).id,'abort');
}
