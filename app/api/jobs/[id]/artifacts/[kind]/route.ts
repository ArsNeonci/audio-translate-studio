import { artifactResponse } from "@/lib/artifacts";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request, context: { params: Promise<{ id: string; kind: string }> }) {
  const { id, kind } = await context.params;
  return artifactResponse(request, id, kind);
}
