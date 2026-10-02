"use client";
import {useLicense} from "@/app/components/license-status";
import { useEffect, useState } from "react";
import PipelineStatus from "./pipeline-status";
import type { Artifact, Job } from "@/lib/jobs";
import StepErrors from "./step-errors";
import Link from "next/link";

const artifacts: [Artifact, string][] = [["zh", "Chinese Transcript"], ["vi", "Vietnamese Transcript"], ["moderated", "Moderated Vietnamese"], ["voice", "Vietnamese Voice"]];


function Preview({ url }: { url: string }) {
  const [text, setText] = useState("Đang tải bản xem trước…");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`${url}?preview=1`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Không đọc được transcript.");
        const content = await response.text();
        if (!controller.signal.aborted) setText(content || "Không có lời nói trong bản chép.");
      } catch (e) { if (!controller.signal.aborted) setText(e instanceof Error ? e.message : "Lỗi tải transcript."); }
    }
    void load();
    return () => controller.abort();
  }, [url]);
  return <div className="transcript-body">{text}</div>;
}

export default function JobDetail({ job, onClose }: { job: Job; onClose: () => void }) {
  const license = useLicense();
  const [preview, setPreview] = useState<Artifact | null>(null);
  return <section className="job-detail" aria-label="Job detail">
    <div className="detail-heading"><div><span className="eyebrow">JOB DETAIL</span><h3>{job.name}</h3><small>{job.id}</small></div><button className="text-button" onClick={onClose}>Đóng</button></div>
    <PipelineStatus job={job} />
    <StepErrors job={job} />
    <p><Link className="text-button" href={`/history/${job.id}`}>Open in History →</Link></p>
    {job.error && <p className="alert" role="alert">{job.failed_stage ? `${job.failed_stage}: ` : ""}{job.error}</p>}
    <div className="artifact-grid">{artifacts.map(([kind, label]) => {
      const url = `/api/jobs/${job.id}/artifacts/${kind}`;
      const ready = job.artifacts?.[kind];
      return <article className={`artifact-card ${ready ? "ready" : ""}`} key={kind}><div><span className="artifact-state">{ready ? "SẴN SÀNG" : "CHƯA CÓ OUTPUT"}</span><h4>{label}</h4></div>
        {ready ? <>{kind === "voice" ? (license.allowed ? <audio controls preload="metadata" src={url} aria-label="Vietnamese voice" /> : <p>License cần ACTIVE để phát audio.</p>) :
          <button className="text-button" disabled={!license.allowed} onClick={() => setPreview(preview === kind ? null : kind)}>{preview === kind ? "Close view" : "View"}</button>}
          <div className="artifact-links"><a href={`${url}?download=1`}>Download {kind === "voice" ? "WAV" : "MD"} ↓</a>
            {kind !== "voice" && <a href={`${url}?format=jsonl&download=1`}>JSONL ↓</a>}</div></> : <p>Sẽ xuất hiện khi bước xử lý hoàn tất.</p>}
      </article>;
    })}</div>
    {license.allowed && preview && job.artifacts?.[preview] && <div className="transcript-panel"><div className="transcript-head"><strong>{artifacts.find(([key]) => key === preview)?.[1]}</strong></div>
      <Preview key={preview} url={`/api/jobs/${job.id}/artifacts/${preview}`} /></div>}
  </section>;
}
