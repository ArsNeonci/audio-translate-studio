import { artifactResponse } from "@/lib/server/artifacts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  return artifactResponse(request, (await context.params).id, "zh");
}
