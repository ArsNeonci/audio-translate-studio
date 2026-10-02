import { rulesResponse } from "@/lib/rules";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET() { return rulesResponse("list"); }
export async function POST(request: Request) { return rulesResponse("add", request); }
