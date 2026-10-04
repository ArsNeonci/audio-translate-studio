"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import { useEffect, useState } from "react";
import Link from "next/link";

export type LicenseStatus = {status: string; expires_at?: string; sequence?: number};
export function useLicense() {
  const [license, setLicense] = useState<LicenseStatus>({status: "CHECKING"});
  useEffect(() => {
    let disposed = false;
    const load = async () => {try {const response = await fetch("/api/license", {cache: "no-store"}); const data = await response.json(); if (!disposed) setLicense(data);} catch {if (!disposed) setLicense({status: "INVALID"});}};
    void load(); const timer = setInterval(() => void load(), 15000);
    return () => {disposed = true; clearInterval(timer);};
  }, []);
  return {...license, allowed: license.status === "ACTIVE"};
}
export default function LicenseBanner() {
  const { tr } = useLanguage();
  const license = useLicense();
  return <p className={license.allowed ? "license-banner" : "alert"}><span>{tr("License:")} {tr(license.status)}</span><span aria-hidden="true"> · </span><Link href="/license">{tr("Kích hoạt / Gia hạn")}</Link>{!license.allowed && tr(" · Bạn vẫn có thể mở History và tải file đã tạo.")}</p>;
}
