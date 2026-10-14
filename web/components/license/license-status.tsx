"use client";
import { apiFetch } from "@audio/ui";
import { useLanguage } from "@/lib/i18n/language-context";
import { useEffect, useState } from "react";
import Link from "next/link";

/** lease: the short online access token (VALID/GRACE/EXPIRED/NONE/REVOKED); perpetual: the licence never ends (expiry year 2100 or later). */
export type LicenseStatus = {status: string; expires_at?: string; sequence?: number; edition?: "basic" | "plus"; lease?: string | null; perpetual?: boolean};
/** A valid licence whose lease lapsed because the app was offline too long: only going online is needed. */
export const leaseOffline = (license: LicenseStatus) => license.status === "ACTIVE" && license.lease === "EXPIRED";

/** Asks for a new lease now (after the person went online) and returns the new status. */
export async function recheckLease(): Promise<LicenseStatus> {
  const response = await apiFetch("/api/license/lease", {method: "POST", cache: "no-store"});
  return response.json();
}

export function useLicense() {
  const [license, setLicense] = useState<LicenseStatus>({status: "CHECKING"});
  useEffect(() => {
    let disposed = false;
    const load = async () => {try {const response = await apiFetch("/api/license", {cache: "no-store"}); const data = await response.json(); if (!disposed) setLicense(data);} catch {if (!disposed) setLicense({status: "INVALID"});}};
    void load(); const timer = setInterval(() => void load(), 15000);
    return () => {disposed = true; clearInterval(timer);};
  }, []);
  // allowed stays the licence itself: finished results still play while offline; new runs are refused by the server with LEASE_OFFLINE.
  return {...license, allowed: license.status === "ACTIVE", setLicense};
}

/** The message and "Check again" button shown while the lease lapsed offline. */
export function LeaseOfflineNotice({license, onChange}: {license: LicenseStatus; onChange: (next: LicenseStatus) => void}) {
  const { tr } = useLanguage();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  if (!leaseOffline(license) && !note) return null;
  async function check() {
    setBusy(true); setNote("");
    try { const next = await recheckLease(); onChange(next); setNote(leaseOffline(next) ? "leaseStillOffline" : "leaseBack"); }
    catch { setNote("leaseStillOffline"); }
    finally { setBusy(false); }
  }
  return <div className={leaseOffline(license) ? "alert lease-offline" : "license-banner"} role="status">
    {leaseOffline(license) && <span>{tr("LEASE_OFFLINE")} </span>}
    {leaseOffline(license) && <button type="button" className="action-button" disabled={busy} onClick={() => void check()}>{tr(busy ? "leaseChecking" : "leaseRecheck")}</button>}
    {note && <span> {tr(note)}</span>}
  </div>;
}

export default function LicenseBanner() {
  const { tr } = useLanguage();
  const license = useLicense();
  if (leaseOffline(license)) return <LeaseOfflineNotice license={license} onChange={license.setLicense} />;
  return <p className={license.allowed ? "license-banner" : "alert"}><span>{tr("License:")} {tr(license.status)}</span>{license.edition&&<><span aria-hidden="true"> · </span><span>{tr("Gói:")} {tr(`edition.${license.edition}`)}</span></>}<span aria-hidden="true"> · </span><Link href="/license">{tr(license.perpetual ? "Giấy phép" : "Kích hoạt / Gia hạn")}</Link>{!license.allowed && tr(" · Bạn vẫn có thể mở History và tải file đã tạo.")}</p>;
}
