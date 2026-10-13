"use client";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import SiteHeader from "@/components/layout/site-header";
import HistoryDetail from "@/components/history/history-detail";
import { useLanguage } from "@/lib/i18n/language-context";

// A static export has no page per workflow, so the detail page takes the id from the address: /history/view?id=... and /tools/view?id=...
function Detail({ scope }: { scope: "history" | "tools" }) {
  const id = useSearchParams().get("id") || "";
  const { tr } = useLanguage();
  return id ? <HistoryDetail key={id} id={id} scope={scope} /> : <p className="alert" role="alert">{tr("Job không tồn tại.")}</p>;
}

export default function HistoryDetailPage({ scope }: { scope: "history" | "tools" }) {
  return <main className="studio"><SiteHeader /><Suspense fallback={null}><Detail scope={scope} /></Suspense></main>;
}
