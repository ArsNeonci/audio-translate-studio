import {managementResponse} from '@/lib/server/management';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function POST(request:Request,context:{params:Promise<{id:string}>}){
  return managementResponse(request,(await context.params).id,'pause');
}
