"use client";
import { useCallback, useEffect, useState } from "react";
import type { Rule } from "@/lib/rules";
import {useNotice} from './use-notice';

export default function RulesPanel({ moderating }: { moderating: boolean }) {
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
    } catch (e) { setLoaded(false); setError(e instanceof Error ? e.message : "Không tải được rules."); }
  }, [setError]);
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
      if (!response.ok) throw new Error(data.error || "Không lưu được rule.");
      setRules(data.rules); setEditing(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Lỗi lưu rule."); }
    finally { setBusy(false); await refresh(); }
  }
  return <section className="rules-section" aria-labelledby="rules-title">
    <div className="section-head"><div><span className="eyebrow">BEFORE THE VOICE</span><h2 id="rules-title">Community Moderation Rules</h2></div>
      <button className="action-button" disabled={disabled} onClick={() => edit()}>Add Rule</button></div>
    <p className="section-description">Thay từ và cụm từ trong bản dịch trước khi tạo giọng đọc. Mỗi job giữ danh sách rules tại thời điểm bắt đầu moderation.</p>
    {(locked || moderating) && <p className="lock-notice" role="status">Replacement rules are locked while moderation is running.</p>}
    {error && <p className="alert" role="alert">{error}</p>}
    <div className="table-wrap"><table className="rules-table"><thead><tr><th>Original</th><th>Replacement</th><th>Actions</th></tr></thead><tbody>
      {rules.map(rule => <tr key={rule.id}><td>{rule.source}</td><td>{rule.replacement || <em>Để trống</em>}</td><td className="rule-actions">
        <button disabled={disabled} onClick={() => edit(rule)}>Edit</button><button disabled={disabled} onClick={() => void mutate("DELETE", rule.id)}>Delete</button>
      </td></tr>)}
    </tbody></table>{!rules.length && <div className="rules-empty">{loaded ? "Chưa có rule. Bản dịch sẽ được giữ nguyên, chỉ chuẩn hóa Unicode." : "Đang tải rules…"}</div>}</div>
    {editing && <form className="rule-form" onSubmit={e => { e.preventDefault(); void mutate(editing === "new" ? "POST" : "PUT", editing === "new" ? undefined : editing); }}>
      <fieldset disabled={disabled}><legend>{editing === "new" ? "Add Rule" : "Edit Rule"}</legend>
        <label>Original<input required maxLength={1000} value={source} onChange={e => setSource(e.target.value)} /></label>
        <label>Replacement<input maxLength={10000} value={replacement} onChange={e => setReplacement(e.target.value)} /></label>
        <div className="form-actions"><button className="action-button" type="submit">{busy ? "Saving…" : "Save"}</button>
          <button type="button" className="text-button" onClick={() => setEditing(null)}>Cancel</button></div>
      </fieldset>
    </form>}
  </section>;
}
