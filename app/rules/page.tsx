import SiteHeader from "@/app/components/site-header";
import RulesPanel from "@/app/components/rules-panel";
export default function RulesPage() {
  return <main className="studio"><SiteHeader /><RulesPanel moderating={false} /></main>;
}
