import { pythonCommand } from "@/lib/server/worker-client";

export type Rule = { id: string; source: string; replacement: string };
type RuleResponse = { status: number; rules?: Rule[]; locked?: boolean; error?: string };

export function rulesCommand(payload: Record<string, unknown>): Promise<RuleResponse> {
  return pythonCommand<RuleResponse>("rules.py", payload);
}

export async function rulesResponse(action: string, request?: Request, id?: string) {
  try {
    let payload: Record<string, unknown> = {};
    if (request && action !== "delete") {
      const text = await request.text();
      if (text.length > 24000) return Response.json({ error: "Rule quá dài." }, { status: 400 });
      try { payload = JSON.parse(text); } catch { return Response.json({ error: "JSON không hợp lệ." }, { status: 400 }); }
      if (!payload || Array.isArray(payload) || typeof payload !== "object") return Response.json({ error: "JSON object required." }, { status: 400 });
    }
    const { status, ...body } = await rulesCommand({ source: payload.source, replacement: payload.replacement, action, id });
    return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Không thể kết nối replacement rules service." }, { status: 500 });
  }
}
