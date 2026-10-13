"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import SiteHeader from "@/components/layout/site-header";
import HistoryList from "@/components/history/history-list";

export default function HistoryPage() {
  const { tr } = useLanguage();
  return <main className="studio"><SiteHeader /><section className="history-heading"><span className="eyebrow">{tr("SAVED RESULTS")}</span><h1>{tr("History")}</h1><p>{tr("Các kết quả đã lưu, sẵn sàng xem và tải xuống.")}</p></section><HistoryList /></main>;
}
