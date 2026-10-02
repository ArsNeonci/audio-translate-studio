import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {previewRoot, voiceSamples} from '@/lib/voice-previews';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(_request:Request, context:{params:Promise<{key:string}>}) {
  const {key}=await context.params;
  if (!/^[a-f0-9]{64}$/.test(key) || !(await voiceSamples()).some(item=>item.key===key)) return Response.json({error:'Mẫu giọng chưa sẵn sàng'},{status:404});
  const file=await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ previewRoot, `${key}.wav`)).catch(()=>null);
  if (!file) return Response.json({error:'Không tìm thấy mẫu giọng'},{status:404});
  return new Response(new Uint8Array(file), {headers:{'Content-Type':'audio/wav','Content-Length':String(file.length),'Cache-Control':'public, max-age=31536000, immutable','X-Content-Type-Options':'nosniff'}});
}
