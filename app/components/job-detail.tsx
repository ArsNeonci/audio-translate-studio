"use client";
import { useLanguage } from "@/lib/language-context";
import {useLicense} from "@/app/components/license-status";
import { useEffect, useState } from "react";
import PipelineStatus from "./pipeline-status";
import type { Artifact, Job } from "@/lib/jobs";
import StepErrors from "./step-errors";
import Link from "next/link";

const artifacts: [Artifact, string][] = [["zh", "Chinese Transcript"], ["vi", "Vietnamese Transcript"], ["moderated", "Moderated Vietnamese"], ["voice", "Vietnamese Voice"]];


function Preview({ url }: { url: string }) {
  const { tr } = useLanguage();
  const [text, setText] = useState(tr("Đang tải bản xem trước…"));
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`${url}?preview=1`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(tr("Không đọc được transcript."));
        const content = await response.text();
        if (!controller.signal.aborted) setText(content || tr("Không có lời nói trong bản chép."));
      } catch (e) { if (!controller.signal.aborted) setText(e instanceof Error ? e.message : tr("Lỗi tải transcript.")); }
    }
    void load();
    return () => controller.abort();
  }, [url,tr]);
  return <div className="transcript-body">{text}</div>;
}

export default function JobDetail({ job, onClose }: { job: Job; onClose: () => void }) {
  const { tr } = useLanguage();
  const license = useLicense();
  const [preview, setPreview] = useState<Artifact | null>(null);
  return <section className="job-detail" aria-label={tr("Job detail")}>
    <div className="detail-heading"><div><span className="eyebrow">{tr("JOB DETAIL")}</span><h3>{job.name}</h3><small>{job.id}</small></div><button className="text-button" onClick={onClose}>{tr("Đóng")}</button></div>
    <PipelineStatus job={job} />
    <StepErrors job={job} />
    <p><Link className="text-button" href={`/history/${job.id}`}>{tr("Open in History →")}</Link></p>
    {job.error && <p className="alert" role="alert">{job.failed_stage ? `${tr(job.failed_stage.toUpperCase())}: ` : ""}{tr(job.error)}</p>}
    <div className="artifact-grid">{artifacts.map(([kind, label]) => {
      const url = `/api/jobs/${job.id}/artifacts/${kind}`;
      const ready = job.artifacts?.[kind];
      return <article className={`artifact-card ${ready ? "ready" : ""}`} key={kind}><div><span className="artifact-state">{ready ? tr("SẴN SÀNG") : tr("CHƯA CÓ OUTPUT")}</span><h4>{tr(label)}</h4></div>
        {ready ? <>{kind === "voice" ? (license.allowed ? <audio controls preload="metadata" src={url} aria-label={tr("Vietnamese voice")} /> : <p>{tr("License cần ACTIVE để phát audio.")}</p>) :
          <button className="text-button" disabled={!license.allowed} onClick={() => setPreview(preview === kind ? null : kind)}>{preview === kind ? tr("Close view") : tr("View")}</button>}
          <div className="artifact-links"><a href={`${url}?download=1`}>{tr("Download")} {kind === "voice" ? "WAV" : "MD"} ↓</a>
            {kind !== "voice" && <a href={`${url}?format=jsonl&download=1`}>JSONL ↓</a>}</div></> : <p>{tr("Sẽ xuất hiện khi bước xử lý hoàn tất.")}</p>}
      </article>;
    })}</div>
    {license.allowed && preview && job.artifacts?.[preview] && <div className="transcript-panel"><div className="transcript-head"><strong>{tr(artifacts.find(([key]) => key === preview)?.[1] || "")}</strong></div>
      <Preview key={preview} url={`/api/jobs/${job.id}/artifacts/${preview}`} /></div>}
  </section>;
}
