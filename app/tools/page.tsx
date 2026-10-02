"use client";
import { useState } from "react";
import SiteHeader from "@/app/components/site-header";
import VoiceSelect from "@/app/components/voice-select";
import HistoryList from "@/app/components/history-list";
import { useLicense } from "@/app/components/license-status";
import { useNotice } from '@/app/components/use-notice';
const tools = [{ id: "transcription", label: "Chinese Audio → Chinese Text" }, { id: "translation", label: "Chinese Text → Vietnamese Text" }, { id: "moderation", label: "Vietnamese Text → Moderated Vietnamese" }, { id: "tts", label: "Vietnamese Text → Vietnamese Voice" }];
export default function Tools() {
  const license = useLicense(); const [tool, setTool] = useState("translation"), [voice, setVoice] = useState(""), [file, setFile] = useState<File | null>(null), [busy, setBusy] = useState(false), [version, setVersion] = useState(0); const [message, setMessage] = useNotice();
  async function run(e: React.FormEvent) { e.preventDefault(); if (!file) return; setBusy(true); setMessage(""); try { const p = new URLSearchParams({ tool, name: file.name, voice }); const r = await fetch(`/api/tools?${p}`, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file }); const d = await r.json(); if (!r.ok) throw new Error(d.error); setMessage("Tool run đã được thêm vào hàng đợi."); setVersion(v => v + 1); } catch (e) { setMessage(e instanceof Error ? e.message : "Upload thất bại."); } finally { setBusy(false); } }
  return <main className="studio"><SiteHeader /><section className="hero"><span className="eyebrow">STANDALONE TOOLS</span><h1>Sử dụng tool đơn</h1><p>Dùng lại các adapter của workflow. Audio tối đa 2 GiB; UTF-8 TXT/MD/JSONL tối đa 64 MiB, mỗi dòng tối đa 64 KiB.</p><div className="tool-cards">{tools.map(t => <button type="button" className={`tool-card ${tool === t.id ? "selected" : ""}`} aria-pressed={tool === t.id} key={t.id} onClick={() => { setTool(t.id); setFile(null); }}>{t.label}</button>)}</div><form onSubmit={run} className="tool-form"><label>Input file<input key={tool} type="file" required accept={tool === "transcription" ? ".wav,.mp3,.m4a,.flac,.ogg,.aac,.webm,.mp4" : ".txt,.md,.jsonl"} onChange={e => setFile(e.target.files?.[0] || null)} /></label>{tool === "tts" && <VoiceSelect value={voice} onChange={setVoice} />}<button disabled={busy || !license.allowed || !file}>{busy ? "Đang upload…" : "Run"}</button></form>{message && <p className="alert" role="status">{message}</p>}</section><h2>Tool History</h2><HistoryList scope="tools" refreshVersion={version} /></main>;
}
