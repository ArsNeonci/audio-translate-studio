"use client";
import { useCallback, useEffect, useState } from "react";
import type { Rule } from "@/lib/rules";
import {useNotice} from './use-notice';
import { useLanguage } from '@/lib/language-context';

export default function RulesPanel({ moderating }: { moderating: boolean }) {
  const { t , tr} = useLanguage();
  const [rules, setRules] = useState<Rule[]>([]);
  const [locked, setLocked] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [source, setSource] = useState("");
  const [replacement, setReplacement] = useState("");
  const [error, setError] = useNotice();
  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/rules", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      setRules(data.rules); setLocked(data.locked); setLoaded(true);
    } catch (e) { setLoaded(false); setError(e instanceof Error ? e.message : tr("Không tải được rules.")); }
  }, [setError,tr]);
  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0);
    const timer = setInterval(() => void refresh(), 3000);
    return () => { clearTimeout(first); clearInterval(timer); };
  }, [refresh]);
  const disabled = busy || locked || moderating || !loaded;
  function edit(rule?: Rule) {
    setEditing(rule?.id || "new"); setSource(rule?.source || ""); setReplacement(rule?.replacement || ""); setError("");
  }
  async function mutate(method: string, id?: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/rules${id ? `/${id}` : ""}`, { method,
        headers: { "Content-Type": "application/json" }, body: method === "DELETE" ? undefined : JSON.stringify({ source, replacement }) });
      const data = await response.json();
      if (data.locked) setLocked(true);
      if (!response.ok) throw new Error(data.error || tr("Không lưu được rule."));
      setRules(data.rules); setEditing(null);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Lỗi lưu rule.")); }
    finally { setBusy(false); await refresh(); }
  }
  return <section className="rules-section" aria-labelledby="rules-title">
    <div className="section-head"><div><span className="eyebrow">{tr("BEFORE THE VOICE")}</span><h2 id="rules-title">{tr("Community Moderation Rules")}</h2></div>
      <button className="action-button" disabled={disabled} onClick={() => edit()}>{tr("Add Rule")}</button></div>
    <p className="section-description">{tr("Thay từ và cụm từ trong bản dịch trước khi tạo giọng đọc. Mỗi job giữ danh sách rules tại thời điểm bắt đầu moderation.")}</p>
    {(locked || moderating) && <p className="lock-notice" role="status">{tr("Replacement rules are locked while moderation is running.")}</p>}
    {error && <p className="alert" role="alert">{error}</p>}
    <div className="table-wrap"><table className="rules-table"><thead><tr><th>{tr("Original")}</th><th>{tr("Replacement")}</th><th>{tr("Actions")}</th></tr></thead><tbody>
      {rules.map(rule => <tr key={rule.id}><td>{rule.source}</td><td>{rule.replacement || <em>{tr("Để trống")}</em>}</td><td className="rule-actions">
        <div className="rule-action-group">
          <button type="button" className="rule-icon" disabled={disabled} aria-label={t.rules.edit} title={t.rules.edit} onClick={() => edit(rule)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m16 3 5 5-12 12-6 1 1-6Z"/><path d="m14 5 5 5"/></svg>
          </button>
          <button type="button" className="rule-icon rule-icon-delete" disabled={disabled} aria-label={t.rules.delete} title={t.rules.delete} onClick={() => void mutate("DELETE", rule.id)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg>
          </button>
        </div>
      </td></tr>)}
    </tbody></table>{!rules.length && <div className="rules-empty">{loaded ? tr("Chưa có rule. Bản dịch sẽ được giữ nguyên, chỉ chuẩn hóa Unicode.") : tr("Đang tải rules…")}</div>}</div>
    {editing && <form className="rule-form" onSubmit={e => { e.preventDefault(); void mutate(editing === "new" ? "POST" : "PUT", editing === "new" ? undefined : editing); }}>
      <fieldset disabled={disabled}><legend>{editing === "new" ? tr("Add Rule") : tr("Edit Rule")}</legend>
        <label>{tr("Original")}<input required maxLength={1000} value={source} onChange={e => setSource(e.target.value)} /></label>
        <label>{tr("Replacement")}<input maxLength={10000} value={replacement} onChange={e => setReplacement(e.target.value)} /></label>
        <div className="form-actions"><button className="action-button" type="submit">{busy ? tr("Saving…") : tr("Save")}</button>
          <button type="button" className="text-button" onClick={() => setEditing(null)}>{tr("Cancel")}</button></div>
      </fieldset>
    </form>}
  </section>;
}
