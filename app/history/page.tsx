import SiteHeader from "@/app/components/site-header";
import HistoryList from "@/app/components/history-list";

export default function HistoryPage() {
  return <main className="studio"><SiteHeader /><section className="history-heading"><span className="eyebrow">SAVED RESULTS</span><h1>History</h1><p>Các kết quả đã lưu, sẵn sàng xem và tải xuống.</p></section><HistoryList /></main>;
}
