"use client";
import {useLicense} from "@/app/components/license-status";
import { useEffect, useState } from "react";
import PipelineStatus from "./pipeline-status";
import StepErrors from "./step-errors";
import {runNumber} from "@/lib/format";
import Link from "next/link";
import type { HistoryFile, HistoryJob } from "@/lib/history";

const labels: Record<string, string> = {ZH_JSONL: "Chinese JSONL", ZH_MD: "Chinese Markdown", VI_JSONL: "Vietnamese JSONL", VI_MD: "Vietnamese Markdown", MODERATED_JSONL: "Moderated Vietnamese JSONL", MODERATED_MD: "Moderated Vietnamese Markdown", MODERATION_RESULT: "Moderation Result", VOICE_WAV: "Vietnamese Voice", VOICE_MANIFEST: "Voice Manifest", ZH_TXT: "Chinese Text", VOICE_M4A: "Vietnamese Voice"};
const size = (bytes: number) => bytes < 1048576 ? `${(bytes/1024).toFixed(1)} KB` : `${(bytes/1048576).toFixed(1)} MB`;
type Chunk = {content: string; offset: number; next_offset: number | null; size: number};

function FilePreview({id,file,scope}: {id:string;file:HistoryFile;scope:"history"|"tools"}) {
  const [offsets, setOffsets] = useState([0]);
  const [chunk, setChunk] = useState<Chunk | null>(null);
  const [error, setError] = useState("");
  const offset = offsets[offsets.length-1];
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`/api/${scope}/${id}/files/${file.id}?preview=1&offset=${offset}`, {cache: "no-store", signal: controller.signal});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (file.path.endsWith(".jsonl")) data.content = data.content.split("\n").map((line: string) => {try {return line ? JSON.stringify(JSON.parse(line), null, 2) : "";} catch {return line;}}).join("\n");
        setChunk(data); setError("");
      } catch(e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Không xem được file.");}
    }
    void load(); return () => controller.abort();
  }, [id, file.id, file.path, offset,scope]);
  const ready = chunk?.offset === offset;
  return <section className="transcript-panel"><div className="transcript-head"><strong>{labels[file.type]}</strong><span>{size(file.size)} · Phần {offsets.length}</span></div>{error ? <p className="alert">{error}</p> : <pre className="transcript-body">{ready ? chunk.content : "Đang tải…"}</pre>}
    <div className="history-pagination"><button className="text-button" disabled={offsets.length === 1} onClick={() => setOffsets(v => v.slice(0,-1))}>← Previous chunk</button><span>Đọc tối đa 64 KB mỗi lần</span><button className="text-button" disabled={!ready || chunk?.next_offset == null} onClick={() => {if (chunk?.next_offset != null) setOffsets(v => [...v, chunk.next_offset!]);}}>Next chunk →</button></div>
  </section>;
}

export default function HistoryDetail({id,scope="history"}: {id:string;scope?:"history"|"tools"}) {
  const license = useLicense();
  const [job, setJob] = useState<HistoryJob | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<HistoryFile | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`/api/${scope}/${id}`, {cache: "no-store", signal: controller.signal});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        setJob(data.job); setError("");
      } catch(e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Không tải được job.");}
    }
    void load(); const timer = setInterval(() => void load(), 5000);
    return () => {controller.abort(); clearInterval(timer);};
  }, [id,scope]);
  return <section className="history-detail"><Link className="text-button" href={`/${scope}`}>← History</Link>{error && <p className="alert" role="alert">{error}</p>}{!job && !error && <p role="status">Đang tải kết quả…</p>}
    {job && <><div className="history-heading"><span className="eyebrow">SAVED JOB · {job.status}</span><h1>#{runNumber(job.workflow_no)} · {job.name}</h1><small>{id}</small><p>{job.url}</p></div>
      <PipelineStatus job={job} />
      <StepErrors job={job} />
      {["TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"].map(step => {
        const files = job.files.filter(file => file.step === step);
        if (!files.length) return null;
        return <section className="history-stage" key={step}><h2>{step === "TTS" ? "TTS" : step.charAt(0)+step.slice(1).toLowerCase()}</h2><div className="artifact-grid">{files.map(file => {
          const url = `/api/${scope}/${id}/files/${file.id}`;
          const audio = /\.(wav|m4a)$/.test(file.path);
          return <article className="artifact-card ready" key={file.id}><span className="artifact-state">{file.status} · {size(file.size)}</span><h4>{labels[file.type] || file.type}</h4>
            {file.status!=="AVAILABLE"?<p>{file.status} · Kết quả cần được tạo lại.</p>:audio ? (license.allowed ? <audio controls preload="metadata" src={url} aria-label={labels[file.type]} /> : <p>License cần ACTIVE để phát audio.</p>) : <button className="text-button" disabled={!license.allowed} onClick={() => setSelected(selected?.id === file.id ? null : file)}>{selected?.id === file.id ? "Close view" : "View"}</button>}
            <div className="artifact-links">{file.status==="AVAILABLE"&&<a href={scope==="tools"?`${url}?download=1`:`${url}/download`}>Download ↓</a>}</div><small>{file.path}</small></article>;
        })}</div></section>;
      })}
      {!job.files.length && <div className="empty"><strong>Chưa có file hoàn thành.</strong></div>}
      {license.allowed && selected && job.files.some(file => file.id === selected.id&&file.status==="AVAILABLE") && <FilePreview key={selected.id} id={id} file={selected} scope={scope} />}
    </>}
  </section>;
}
