import { pythonCommand } from "@/lib/server/worker-client";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { status, ...body } = await pythonCommand<{status: number; errors?: unknown[]; error?: string}>("retry.py", {action: "errors", id: (await context.params).id});
    return Response.json(body, {status, headers: {"Cache-Control": "no-store"}});
  } catch { return Response.json({error: "Error service unavailable. Check PYTHON_BIN and .venv."}, {status: 503}); }
}
