"use client";
import { useLanguage } from "@/lib/language-context";
import SiteHeader from "@/app/components/site-header";
import HistoryList from "@/app/components/history-list";

export default function HistoryPage() {
  const { tr } = useLanguage();
  return <main className="studio"><SiteHeader /><section className="history-heading"><span className="eyebrow">{tr("SAVED RESULTS")}</span><h1>{tr("History")}</h1><p>{tr("Các kết quả đã lưu, sẵn sàng xem và tải xuống.")}</p></section><HistoryList /></main>;
}
