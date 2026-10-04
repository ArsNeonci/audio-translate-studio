import SiteHeader from "@/components/layout/site-header";
import RulesPanel from "@/components/rules/rules-panel";
export default function RulesPage() {
  return <main className="studio"><SiteHeader /><RulesPanel moderating={false} /></main>;
}
