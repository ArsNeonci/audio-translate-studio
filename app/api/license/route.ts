import { licenseCommand } from "@/lib/server/license";
import { originAllowed } from "@/lib/server/origin";
import { edition } from "@/lib/server/edition";
import { ensureLease } from "@/lib/server/lease";
import { fetchRenewals } from "@/lib/server/billing-portal";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(request: Request) {
  void ensureLease(); // Opening the app renews the lease in the background when it is due.
  void fetchRenewals(); // Installs a renewal that was paid for in the Billing portal (every few seconds right after it was opened).
  const [result, tier] = await Promise.all([licenseCommand({action:new URL(request.url).searchParams.get("machine") === "1" ? "machine" : "status"}), edition()]);
  return Response.json({...result, edition: tier},{status:result.http_status,headers:{"Cache-Control":"no-store"}});
}
export async function POST(request: Request) {
  if (!originAllowed(request)) return Response.json({error:"Origin rejected"},{status:403});
  try {
    const text = await request.text(); if (text.length>34000) return Response.json({error:"Token quá dài."},{status:400});
    const data = JSON.parse(text);
    if (!["activate","renew"].includes(data.action) || typeof data.token !== "string") return Response.json({error:"Invalid request"},{status:400});
    const result = await licenseCommand({action:data.action,token:data.token.trim()});
    if (result.status === "ACTIVE") void ensureLease(true); // Fresh license: fetch its lease now.
    return Response.json(result,{status:result.http_status,headers:{"Cache-Control":"no-store"}});
  } catch {return Response.json({error:"Invalid request"},{status:400});}
}
