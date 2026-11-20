"use client";
import { apiFetch, apiUrl, AudioPlayer, DownloadIcon } from "@audio/ui";
import { useLanguage } from "@/lib/i18n/language-context";
import {useLicense} from "@/components/license/license-status";
import { useEffect, useState } from "react";
import PipelineStatus from "@/components/workflow/pipeline-status";
import StepErrors from "@/components/workflow/step-errors";
import {runNumber} from "@/lib/shared/format";
import Link from "next/link";
import type { HistoryFile, HistoryJob } from "@/lib/shared/job-types";
import { VideoResult } from "@/components/video/video-picker";

const labels: Record<string, string> = {SOURCE_AUDIO: "Chinese Source Audio", ZH_JSONL: "Chinese JSONL", ZH_MD: "Chinese Markdown", VI_JSONL: "Vietnamese JSONL", VI_MD: "Vietnamese Markdown", MODERATED_JSONL: "Moderated Vietnamese JSONL", MODERATED_MD: "Moderated Vietnamese Markdown", MODERATION_RESULT: "Moderation Result", VOICE_WAV: "Vietnamese Voice", VOICE_MANIFEST: "Voice Manifest", VIDEO_MP4: "VIDEO_MP4", SUBTITLE_SRT: "SUBTITLE_SRT", ZH_TXT: "Chinese Text", SPLIT_ZIP: "splitZip", VOICE_M4A: "Vietnamese Voice"};
/** The name of a result file: the fixed names, or "Part 3" for the parts tool 7 makes (SPLIT_003). */
const labelOf = (tr: (text: string, values?: Record<string, string | number>) => string, file: HistoryFile) =>
  /^SPLIT_\d+$/.test(file.type) ? `${tr("splitPart")} ${Number(file.type.slice(6))}` : tr(labels[file.type] || file.type);
const size = (bytes: number) => bytes < 1048576 ? `${(bytes/1024).toFixed(1)} KB` : `${(bytes/1048576).toFixed(1)} MB`;
type Chunk = {content: string; offset: number; next_offset: number | null; size: number};

function FilePreview({id,file,scope}: {id:string;file:HistoryFile;scope:"history"|"tools"}) {
  const { tr } = useLanguage();
  const [offsets, setOffsets] = useState([0]);
  const [chunk, setChunk] = useState<Chunk | null>(null);
  const [error, setError] = useState("");
  const offset = offsets[offsets.length-1];
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await apiFetch(`/api/${scope}/${id}/files/${file.id}?preview=1&offset=${offset}`, {cache: "no-store", signal: controller.signal});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (file.path.endsWith(".jsonl")) data.content = data.content.split("\n").map((line: string) => {try {return line ? JSON.stringify(JSON.parse(line), null, 2) : "";} catch {return line;}}).join("\n");
        setChunk(data); setError("");
      } catch(e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : tr("Không xem được file."));}
    }
    void load(); return () => controller.abort();
  }, [id, file.id, file.path, offset,scope,tr]);
  const ready = chunk?.offset === offset;
  return <section className="transcript-panel"><div className="transcript-head"><strong>{labelOf(tr, file)}</strong><span>{size(file.size)} · {tr("Phần")} {offsets.length}</span></div>{error ? <p className="alert">{tr(error)}</p> : <pre className="transcript-body">{ready ? chunk.content : tr("Đang tải…")}</pre>}
    <div className="history-pagination"><button className="text-button" disabled={offsets.length === 1} onClick={() => setOffsets(v => v.slice(0,-1))}>{tr("← Previous chunk")}</button><span>{tr("Đọc tối đa 64 KB mỗi lần")}</span><button className="text-button" disabled={!ready || chunk?.next_offset == null} onClick={() => {if (chunk?.next_offset != null) setOffsets(v => [...v, chunk.next_offset!]);}}>{tr("Next chunk →")}</button></div>
  </section>;
}

export default function HistoryDetail({id,scope="history"}: {id:string;scope?:"history"|"tools"}) {
  const { tr } = useLanguage();
  const license = useLicense();
  const [job, setJob] = useState<HistoryJob | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<HistoryFile | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await apiFetch(`/api/${scope}/${id}`, {cache: "no-store", signal: controller.signal});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        setJob(data.job); setError("");
      } catch(e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : tr("Không tải được job."));}
    }
    void load(); const timer = setInterval(() => void load(), 5000);
    return () => {controller.abort(); clearInterval(timer);};
  }, [id,scope,tr]);
  return <section className="history-detail"><Link className="text-button" href={`/${scope}`}>{tr("← History")}</Link>{error && <p className="alert" role="alert">{tr(error)}</p>}{!job && !error && <p role="status">{tr("Đang tải kết quả…")}</p>}
    {job && <><div className="history-heading"><span className="eyebrow">{tr("SAVED JOB ·")} {tr(job.status)}</span><h1>#{runNumber(job.workflow_no)} · {job.name}</h1><small>{id}</small><p>{job.url}</p></div>
      {!job.tool_type && job.manual_translation && job.status === "COMPLETED" && job.steps?.TRANSLATION?.state !== "COMPLETED" && <p role="note"><small className="manual-hint">{tr("manualWaiting")}</small>{" "}<Link className="text-button" href={`/reprocess?id=${job.id}&step=MODERATION`}>{tr("manualLoadLink")}</Link></p>}
      <PipelineStatus job={job} />
      <StepErrors job={job} />
      {(() => {
        // The JSON of each stage is for programs, not for people: only the readable files are listed (they stay on disk and in the exports).
        const shown = (file: HistoryFile) => !/\.jsonl?$/.test(file.path);
        const stages = ["DOWNLOAD", "TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS", "SUBTITLE", "VIDEO", "BURN", "SPLIT", "RENDER"]
          .map(step => ({ step, files: job.files.filter(file => file.step === step && shown(file)) })).filter(stage => stage.files.length);
        // Two stages per row, in order (text and audio alike). A stage with several files, a video (it needs the width), or one left over, takes a whole row.
        const pairable = (stage: (typeof stages)[number]) => stage.files.length === 1 && !stage.files.some(file => file.type === "VIDEO_MP4" || file.type === "VIDEO_SUB_MP4");
        const rows: (typeof stages)[] = [];
        for (let i = 0; i < stages.length; i++) {
          if (pairable(stages[i]) && i + 1 < stages.length && pairable(stages[i + 1])) { rows.push([stages[i], stages[i + 1]]); i++; } else rows.push([stages[i]]);
        }
        const card = (file: HistoryFile) => {
          const url = apiUrl(`/api/${scope}/${id}/files/${file.id}`);
          const audio = /\.(wav|m4a|mp4|mp3|webm|ogg|opus|flac|aac)$/.test(file.path);
          return <article className="artifact-card ready" key={file.id}><span className="artifact-state">{tr(file.status)} · {size(file.size)}{file.origin === "import" && ` · ${tr("originImport")}`}</span><div className="artifact-file-heading"><h4>{labelOf(tr, file)}</h4>{file.status==='AVAILABLE'&&<a className="rule-icon file-download" href={scope==='tools'?`${url}?download=1`:`${url}/download`} title={tr('Download ↓')} aria-label={`${tr('Download ↓')} ${file.path}`}><DownloadIcon/></a>}</div>
            {file.status!=="AVAILABLE"?<p>{tr(file.status)} · {tr("Kết quả cần được tạo lại.")}</p>:file.type==="VIDEO_MP4"||file.type==="VIDEO_SUB_MP4"?<VideoResult id={id} scope={scope==="tools"?"tools":"workflows"} url={url} subtitled={file.type==="VIDEO_SUB_MP4"} />:file.path.endsWith(".zip") ? <p>{tr("splitZipHelp")}</p> : audio ? (license.allowed ? <AudioPlayer src={url} label={labelOf(tr, file)} /> : <p>{tr("License cần ACTIVE để phát audio.")}</p>) : <button className="text-button" disabled={!license.allowed} onClick={() => setSelected(selected?.id === file.id ? null : file)}>{selected?.id === file.id ? tr("Close view") : tr("View")}</button>}
            {file.type==="SUBTITLE_SRT"&&file.status==="AVAILABLE"&&<small>{tr("subtitleYoutube")}</small>}
            <small>{file.path}</small></article>;
        };
        const previewing = license.allowed && selected && job.files.some(file => file.id === selected.id && file.status === "AVAILABLE") ? selected : null;
        return rows.map(row => <div key={row[0].step}>
          <div className={`history-row${row.length === 1 ? " single" : ""}`}>{row.map(stage => <section className="history-stage" key={stage.step}><h2>{tr(stage.step)}</h2><div className="artifact-grid">{stage.files.map(card)}</div></section>)}</div>
          {previewing && row.some(stage => stage.files.some(file => file.id === previewing.id)) && <FilePreview key={previewing.id} id={id} file={previewing} scope={scope} />}   {/* the text opens right under the row of the file */}
        </div>);
      })()}
      {!job.files.length && <div className="empty"><strong>{tr("Chưa có file hoàn thành.")}</strong></div>}
    </>}
  </section>;
}
