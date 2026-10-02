import SiteHeader from "@/app/components/site-header";
import RulesPanel from "@/app/components/rules-panel";

export default function RulesPage() {
  return (
    <main className="studio">
      <SiteHeader />
      <section className="history-heading">
        <span className="eyebrow">MODERATION</span>
        <h1>Community Rules</h1>
        <p>Thay từ và cụm từ trong bản dịch trước khi tạo giọng đọc.</p>
      </section>
      <RulesPanel moderating={false} />
    </main>
  );
}
