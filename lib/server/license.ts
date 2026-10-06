import { spawnSecurityCore, callSecurityCore } from "@/lib/server/security-core";

export type LicenseStatus = {status: string; allowed?: boolean; expires_at?: string; sequence?: number; error?: string; machine_id?: string; http_status: number};

// Prefer the service pipe; fall back to spawning the CLI binary when the service is absent
// (dev). The binary answers queries in-process; the processing gate is enforced at launch.
export async function licenseCommand(payload: Record<string, unknown>): Promise<LicenseStatus> {
  try { return await callSecurityCore(payload) as unknown as LicenseStatus; }
  catch { return await spawnLicenseCommand(payload); }
}
function spawnLicenseCommand(payload: Record<string, unknown>): Promise<LicenseStatus> {
  return new Promise((resolve) => {
    const child = spawnSecurityCore(payload);
    let output = "";
    const fail = () => resolve({http_status:503,status:"INVALID",error:"License service unavailable."});
    const timeout = setTimeout(() => {child.kill(); fail();},40000);
    child.stdout!.setEncoding("utf8"); child.stdout!.on("data",data => {output += data;if(output.length>65536) child.kill();}); child.stderr!.resume();
    child.on("error",() => {clearTimeout(timeout);fail();});
    child.on("close",code => {clearTimeout(timeout);try {if(code) return fail();resolve(JSON.parse(output));} catch {fail();}});
  });
}
export async function licenseDenial(internet = true): Promise<Response | null> {
  // Admission is the moment a lease matters: refresh it first when it is half used (cached, cheap).
  if (internet) await (await import("@/lib/server/lease")).ensureLease();
  const result = await licenseCommand({action:"check",internet});
  return result.status === "ACTIVE" && result.allowed === true ? null : Response.json({error:result.error || result.status,license_status:result.status},{status:403,headers:{"Cache-Control":"no-store"}});
}
