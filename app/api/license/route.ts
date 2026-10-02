import { licenseCommand } from "@/lib/license";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(request: Request) {
  const result = await licenseCommand({action:new URL(request.url).searchParams.get("machine") === "1" ? "machine" : "status"});
  return Response.json(result,{status:result.http_status,headers:{"Cache-Control":"no-store"}});
}
export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(request.url).origin) return Response.json({error:"Origin rejected"},{status:403});
  try {
    const text = await request.text(); if (text.length>34000) return Response.json({error:"Token quá dài."},{status:400});
    const data = JSON.parse(text);
    if (!["activate","renew"].includes(data.action) || typeof data.token !== "string") return Response.json({error:"Invalid request"},{status:400});
    const result = await licenseCommand({action:data.action,token:data.token.trim()});
    return Response.json(result,{status:result.http_status,headers:{"Cache-Control":"no-store"}});
  } catch {return Response.json({error:"Invalid request"},{status:400});}
}
