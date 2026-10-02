import SiteHeader from "@/app/components/site-header";
import HistoryDetail from "@/app/components/history-detail";

export default async function HistoryJobPage({params}: {params: Promise<{id: string}>}) {
  return <main className="studio"><SiteHeader /><HistoryDetail id={(await params).id} /></main>;
}
