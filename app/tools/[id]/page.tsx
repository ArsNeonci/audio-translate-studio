import SiteHeader from "@/components/layout/site-header";
import HistoryDetail from "@/components/history/history-detail";
export default async function Page({params}:{params:Promise<{id:string}>}){return <main className="studio"><SiteHeader/><HistoryDetail id={(await params).id} scope="tools"/></main>;}
