"use client";
import { useState } from "react";
import SiteHeader from "@/app/components/site-header";
import VoiceSelect from "@/app/components/voice-select";
import HistoryList from "@/app/components/history-list";
import { useLicense } from "@/app/components/license-status";
import { useNotice } from '@/app/components/use-notice';
import FilePicker from '@/app/components/file-picker';
import { useLanguage } from '@/lib/language-context';
const tools = [{ id: "transcription", label: "Chinese Audio → Chinese Text" }, { id: "translation", label: "Chinese Text → Vietnamese Text" }, { id: "moderation", label: "Vietnamese Text → Moderated Vietnamese" }, { id: "tts", label: "Vietnamese Text → Vietnamese Voice" }];
export default function Tools() {
  const { t , tr} = useLanguage();
  const license = useLicense(); const [tool, setTool] = useState("translation"), [voice, setVoice] = useState(""), [file, setFile] = useState<File | null>(null), [busy, setBusy] = useState(false), [version, setVersion] = useState(0); const [message, setMessage] = useNotice();
  async function run(e: React.FormEvent) { e.preventDefault(); if (!file) return; setBusy(true); setMessage(""); try { const p = new URLSearchParams({ tool, name: file.name, voice }); const r = await fetch(`/api/tools?${p}`, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file }); const d = await r.json(); if (!r.ok) throw new Error(d.error); setMessage(tr("Tool run đã được thêm vào hàng đợi.")); setVersion(v => v + 1); } catch (e) { setMessage(e instanceof Error ? e.message : tr("Upload thất bại.")); } finally { setBusy(false); } }
  return <main className="studio"><SiteHeader /><section className="hero"><span className="eyebrow">{t.tools.eyebrow}</span><h1>{t.tools.title}</h1><p>{t.tools.subtitle}</p><div className="tool-cards">{tools.map(item => <button type="button" className={`tool-card ${tool === item.id ? "selected" : ""}`} aria-pressed={tool === item.id} key={item.id} onClick={() => { setTool(item.id); setFile(null); }}>{tr(item.label)}</button>)}</div><form onSubmit={run} className="tool-form"><FilePicker key={tool} accept={tool === "transcription" ? ".wav,.mp3,.m4a,.flac,.ogg,.aac,.webm,.mp4" : ".txt,.md,.jsonl"} file={file} onChange={setFile} />{tool === "tts" && <VoiceSelect value={voice} onChange={setVoice} />}<button disabled={busy || !license.allowed || !file}>{busy ? t.tools.uploading : t.tools.run}</button></form>{message && <p className="alert" role="status">{message}</p>}</section><h2>{t.tools.historyHeading}</h2><HistoryList scope="tools" refreshVersion={version} /></main>;
}
