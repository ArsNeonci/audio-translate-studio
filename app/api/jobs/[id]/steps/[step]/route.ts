import { pythonCommand } from "@/lib/server/worker-client";
import { schedule } from "@/lib/server/jobs";
import { licenseDenial } from "@/lib/server/license";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = {params: Promise<{id: string; step: string}>};
async function command(context: Context, action: string) {
  if (action === "retry") {const denied = await licenseDenial(); if (denied) return denied;}
  try {
    const { id, step } = await context.params;
    const { status, ...body } = await pythonCommand<{status: number; error?: unknown; fix_guide?: unknown}>("retry.py", {action, id, step,fresh:action==='retry'});
    if (status === 202) void schedule();
    return Response.json(body, {status, headers: {"Cache-Control": "no-store"}});
  } catch { return Response.json({error: "Error service unavailable. Check PYTHON_BIN and .venv."}, {status: 503}); }
}
export async function GET(_request: Request, context: Context) { return command(context, "guide"); }
export async function POST(_request: Request, context: Context) { return command(context, "retry"); }
