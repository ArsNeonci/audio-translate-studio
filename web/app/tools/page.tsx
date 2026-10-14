"use client";
import { apiFetch, useNotice, FilePicker } from "@audio/ui";
import { useState } from "react";
import SiteHeader from "@/components/layout/site-header";
import VoiceSelect from "@/components/voice/voice-select";
import HistoryList from "@/components/history/history-list";
import { LeaseOfflineNotice, useLicense } from "@/components/license/license-status";
import AddressProfileSelect from "@/components/voice/address-profile-select";
import TranslationModeSelect from "@/components/voice/translation-mode-select";
import AutoTtsToggle from "@/components/voice/auto-tts-toggle";
import type { TranslationMode } from "@/lib/shared/translation-modes";
import { useLanguage } from '@/lib/i18n/language-context';
import VideoPicker, { emptyVideo, videoPayload, videoReady, type VideoChoice } from "@/components/video/video-picker";
import { useEffect } from "react";
import { runNumber } from "@/lib/shared/format";
const tools = [{ id: "transcription", label: "Chinese Audio → Chinese Text" }, { id: "translation", label: "Chinese Text → Vietnamese Text" }, { id: "moderation", label: "Vietnamese Text → Moderated Vietnamese" }, { id: "tts", label: "Vietnamese Text → Vietnamese Voice" }, { id: "video", label: "Vietnamese Voice + Video → Video" }];
type Voice = { job_id: string; scope: "workflows" | "tools"; workflow_no: number | null; name: string };

/** Tool 5: a voice made by this app (a workflow or tool 4) and the person's clips. */
function VideoTool({ allowed, onQueued, onMessage }: { allowed: boolean; onQueued: () => void; onMessage: (text: string) => void }) {
  const { tr } = useLanguage();
  const [voices, setVoices] = useState<Voice[]>([]), [voiceJob, setVoiceJob] = useState(""), [video, setVideo] = useState<VideoChoice>(emptyVideo), [busy, setBusy] = useState(false);
  useEffect(() => { void apiFetch("/api/video/voices", { cache: "no-store" }).then(r => r.json()).then(d => setVoices(d.voices || [])).catch(() => undefined); }, []);
  async function run(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); onMessage("");
    try {
      const r = await apiFetch("/api/tools", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool: "video", voice_job: voiceJob, video: videoPayload(video) }) });
      const d = await r.json(); if (!r.ok) throw new Error(d.error);
      onMessage(tr("Tool run đã được thêm vào hàng đợi.")); setVideo(emptyVideo()); onQueued();
    } catch (error) { onMessage(error instanceof Error ? tr(error.message) : tr("Upload thất bại.")); } finally { setBusy(false); }
  }
  return <form onSubmit={run} className="tool-form">
    <label>{tr("videoVoice")}<select value={voiceJob} required onChange={e => setVoiceJob(e.target.value)}>
      <option value="">{tr(voices.length ? "videoVoiceChoose" : "videoVoiceNone")}</option>
      {voices.map(v => <option key={v.job_id} value={v.job_id}>{tr(v.scope === "tools" ? "Tool #" : "Workflow #")}{runNumber(v.workflow_no ?? undefined)} · {v.name}</option>)}
    </select></label>
    <VideoPicker value={video} onChange={setVideo} voiceJob={voiceJob || null} disabled={busy} />
    <button disabled={busy || !allowed || !voiceJob || !videoReady(video)}>{tr("videoRun")}</button>
  </form>;
}
export default function Tools() {
  const { t , tr} = useLanguage();
  const license = useLicense(); const [tool, setTool] = useState("translation"), [voice, setVoice] = useState(""), [style, setStyle] = useState(""), [address, setAddress] = useState(""), [mode, setMode] = useState<TranslationMode>("normal"), [auto, setAuto] = useState(false),[source, setSource] = useState<"file" | "link">("file"), [link, setLink] = useState(""), [file, setFile] = useState<File | null>(null), [busy, setBusy] = useState(false), [version, setVersion] = useState(0); const [message, setMessage] = useNotice();
  const byLink = tool === "transcription" && source === "link";
  async function run(e: React.FormEvent) { e.preventDefault(); if (byLink ? !link.trim() : !file) return; setBusy(true); setMessage(""); try { let r: Response; if (byLink) { r = await apiFetch("/api/tools", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool, url: link.trim() }) }); } else { const f = file as File; const p = new URLSearchParams({ tool, name: f.name, voice, ...(tool === "tts" && style ? { style } : {}), ...(tool === "tts" && license.edition === "basic" && auto ? { auto: "1" } : {}),...(tool === "translation" && mode === "genius" ? { mode } : {}), ...(tool === "translation" && mode === "normal" && address ? { address } : {}) }); r = await apiFetch(`/api/tools?${p}`, { method: "POST", headers: { "Content-Type": f.type || "application/octet-stream" }, body: f }); } const d = await r.json(); if (!r.ok) throw new Error(d.error); setMessage(tr("Tool run đã được thêm vào hàng đợi.")); setLink(""); setVersion(v => v + 1); } catch (e) { setMessage(e instanceof Error ? tr(e.message) : tr("Upload thất bại.")); } finally { setBusy(false); } }
  return <main className="studio"><SiteHeader /><section className="hero"><span className="eyebrow">{t.tools.eyebrow}</span><h1>{t.tools.title}</h1><p>{t.tools.subtitle}</p><LeaseOfflineNotice license={license} onChange={license.setLicense} /><div className="tool-cards">{tools.map(item => <button type="button" className={`tool-card ${tool === item.id ? "selected" : ""}`} aria-pressed={tool === item.id} key={item.id} onClick={() => { setTool(item.id); setFile(null); }}>{tr(item.label)}</button>)}</div>{tool === "video" ? <VideoTool allowed={license.allowed} onQueued={() => setVersion(v => v + 1)} onMessage={setMessage} /> : <form onSubmit={run} className="tool-form">{tool === "transcription" && <div className="source-options" role="radiogroup" aria-label={tr("Nguồn âm thanh")}>{(["file", "link"] as const).map(value => <button key={value} type="button" role="radio" aria-checked={source === value} className={`source-chip${source === value ? " selected" : ""}`} onClick={() => setSource(value)}>{value === "file" ? tr("Tệp âm thanh") : tr("Link YouTube")}</button>)}</div>}{byLink ? <input type="url" className="link-input" value={link} onChange={event => setLink(event.target.value)} placeholder="https://www.youtube.com/watch?v=..." aria-label={tr("Link YouTube")} required /> : <FilePicker key={tool} accept={tool === "transcription" ? ".wav,.mp3,.m4a,.flac,.ogg,.aac,.webm,.mp4" : ".txt,.md,.jsonl"} file={file} onChange={setFile} chooseLabel={t.tools.chooseFile} emptyLabel={t.tools.noFileChosen} inputLabel={t.tools.inputFile} />}{tool === "translation" && <TranslationModeSelect value={mode} onChange={setMode} />}{tool === "translation" && mode === "normal" && <AddressProfileSelect value={address} onChange={setAddress} />}{tool === "tts" && <VoiceSelect value={voice} onChange={setVoice} style={style} onStyleChange={setStyle} />}{tool === "tts" && license.edition === "basic" && <AutoTtsToggle checked={auto} onChange={setAuto} />}<button disabled={busy || !license.allowed || (byLink ? !link.trim() : !file)}>{busy ? t.tools.uploading : t.tools.run}</button></form>}{message && <p className="alert" role="status">{message}</p>}</section><h2>{t.tools.historyHeading}</h2><HistoryList scope="tools" refreshVersion={version} /></main>;
}
