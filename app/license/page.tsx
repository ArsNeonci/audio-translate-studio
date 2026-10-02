"use client";
import {useEffect, useState} from "react";
import SiteHeader from "../components/site-header";
import type {LicenseStatus} from "../components/license-status";
import {useNotice} from '../components/use-notice';

export default function LicensePage() {
  const [status, setStatus] = useState<LicenseStatus>({status: "CHECKING"});
  const [machine, setMachine] = useState("");
  const [token, setToken] = useState("");
  const [action, setAction] = useState("activate");
  const [message, setMessage] = useNotice();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let disposed = false;
    void Promise.all([fetch("/api/license", {cache:"no-store"}).then(r=>r.json()), fetch("/api/license?machine=1", {cache:"no-store"}).then(r=>r.json())]).then(([s,m])=>{if (!disposed) {setStatus(s); setMachine(m.machine_id || ""); if (m.error) setMessage(m.error);}}).catch(()=>{if (!disposed) setMessage("Không đọc được trạng thái license.");});
    return () => {disposed = true;};
  }, [setMessage]);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {const response = await fetch("/api/license", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,token:token.trim()})}); const data=await response.json(); if (!response.ok) throw new Error(data.error || data.status); setStatus(data); setToken(""); setMessage("Đã lưu license an toàn trên máy này.");} catch(e) {setMessage(e instanceof Error ? e.message : "Không nhập được license.");} finally {setBusy(false);}
  }
  return <main className="studio"><SiteHeader/><section className="hero"><div className="eyebrow">LICENSE & RENEWAL</div><h1>License của máy này</h1><p role="status">{status.status}{status.sequence ? ` · Sequence ${status.sequence}` : ""}{status.expires_at ? ` · Hết hạn ${new Date(status.expires_at).toLocaleString("vi-VN")}` : ""}</p>
    <label htmlFor="machine-id">Machine ID</label><input id="machine-id" readOnly value={machine} style={{width:"100%"}}/><button className="action-button" disabled={!machine} onClick={()=>void navigator.clipboard.writeText(machine).then(()=>setMessage("Đã copy Machine ID.")).catch(()=>setMessage("Hãy chọn và copy Machine ID."))}>Copy</button>
    <p>Gửi Machine ID cho Admin để nhận token kích hoạt dành riêng cho máy này. Nhập token gia hạn theo thứ tự Admin cấp.</p>
    <form onSubmit={submit}><label htmlFor="license-action">Loại token</label><select id="license-action" value={action} onChange={e=>setAction(e.target.value)}><option value="activate">Kích hoạt lần đầu</option><option value="renew">Gia hạn</option></select><label htmlFor="license-token">Token</label><textarea id="license-token" required value={token} onChange={e=>setToken(e.target.value)} autoComplete="off" spellCheck={false} rows={6} maxLength={34000} style={{width:"100%"}}/><button className="action-button" disabled={busy || !token.trim()}>{busy ? "Đang xác minh…" : "Xác minh và lưu"}</button></form>{message && <p className="alert" role="status">{message}</p>}
  </section></main>;
}
