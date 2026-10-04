import SiteHeader from "@/components/layout/site-header";
import HistoryDetail from "@/components/history/history-detail";

export default async function HistoryJobPage({params}: {params: Promise<{id: string}>}) {
  return <main className="studio"><SiteHeader /><HistoryDetail id={(await params).id} /></main>;
}
