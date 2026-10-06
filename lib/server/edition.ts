import { licenseCommand } from "@/lib/server/license";

export type Edition = "basic" | "plus";
const shared = globalThis as typeof globalThis & {audioEdition?: Promise<Edition>};

// The edition is the Product ID compiled into the native core; it decides how the voice is generated.
export function edition(): Promise<Edition> {
  return shared.audioEdition ??= licenseCommand({action: "identity"}).then(result => {
    const value = result as unknown as {http_status: number; product_id?: string; tier?: string};
    if (value.http_status !== 200 || !value.product_id) throw new Error("identity unavailable");
    return (value.tier ?? (value.product_id.endsWith("-basic") ? "basic" : "plus")) === "plus" ? "plus" : "basic";
  }).catch(() => { shared.audioEdition = undefined; return "basic" as const; });
}
