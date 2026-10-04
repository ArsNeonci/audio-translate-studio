import { rulesResponse } from "@/lib/server/rules";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ id: string }> };
export async function PUT(request: Request, context: Context) {
  return rulesResponse("edit", request, (await context.params).id);
}
export async function DELETE(request: Request, context: Context) {
  return rulesResponse("delete", request, (await context.params).id);
}
