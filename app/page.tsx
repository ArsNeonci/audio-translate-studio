"use client";
import {useLicense} from "@/app/components/license-status";
import LicenseBanner from "@/app/components/license-status";

import { useCallback, useEffect, useState } from "react";
import type { Job } from "@/lib/jobs";
import JobDetail from "@/app/components/job-detail";
import RulesPanel from "@/app/components/rules-panel";
import VoiceSelect from "@/app/components/voice-select";
import {percent,runNumber} from "@/lib/format";
import SiteHeader from "@/app/components/site-header";
import Link from 'next/link';
import {useNotice} from '@/app/components/use-notice';
import WorkflowActions from '@/app/components/workflow-actions';
import { useLanguage } from "@/lib/language-context";

const duration = (ms: number) => ms ? `${Math.floor(ms / 3600000)}h ${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}m` : "—";
type ResourceWarning={reasons:string[];ram_available_gib:number;required_available_gib:number;cpu_percent:number;existing_workflows:number;estimate_basis:string};

export default function Home() {
  const { language, t , tr} = useLanguage();
  const license = useLicense();
  const [url, setUrl] = useState("");
  const [voice,setVoice]=useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useNotice();
  const [selected, setSelected] = useState<string | null>(null);
  const [resourceWarning,setResourceWarning]=useState<ResourceWarning|null>(null);
  const [pendingConvert,setPendingConvert]=useState<{url:string;voice?:string}|null>(null);
  const studioJobs=jobs.filter(job=>job.status!=='COMPLETED');

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/jobs", { cache: "no-store" });
      if (!response.ok) throw new Error(tr("Không tải được danh sách job."));
      setJobs((await response.json()).jobs);
    } catch (error) { setMessage(error instanceof Error ? error.message : tr("Lỗi kết nối.")); }
  }, [setMessage,tr]);

  useEffect(() => {
    const initial = window.setTimeout(() => { setSelected(localStorage.getItem("audio-studio-job")); void refresh(); }, 0);
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);

  async function start(event: React.FormEvent) {
    event.preventDefault();
    await convert({url,voice:voice||undefined});
  }

  async function convert(input:{url:string;voice?:string},queue_only=false){
    if(busy)return;
    setBusy(true); setMessage("");setResourceWarning(null);
    try {
      const response = await fetch("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...input,queue_only }) });
      const data = await response.json();
      if(data.code==='RESOURCE_WARNING'){
        setResourceWarning(data.assessment);setPendingConvert(input);return;
      }
      if (!response.ok) throw new Error(data.error || tr("Không tạo được job."));
      setPendingConvert(null);setUrl(""); await refresh();
      setMessage(t.home.queuedNotice);
    } catch (error) { setMessage(error instanceof Error ? error.message : tr("Không tạo được job.")); }
    finally { setBusy(false); }
  }

  async function retry(id: string) {
    if(!window.confirm(tr("Chạy lại giai đoạn lỗi? Chỉ dữ liệu của giai đoạn này sẽ bị xóa; các bước trước được giữ nguyên.")))return;
    setMessage("");
    try {
      const response = await fetch(`/api/jobs/${id}/retry`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || tr("Không retry được job."));
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : tr("Không retry được job.")); }
  }

  function view(id: string | null) {
    setSelected(id);
    if (id) localStorage.setItem("audio-studio-job", id);
    else localStorage.removeItem("audio-studio-job");
  }

  const getStatusLabel = (job: Job) => {
    if (job.delete_requested) return t.home.deletingWorkflow;
    if (job.pause_requested) return t.home.stoppingAfterTask;
    return t.statusLabels[job.status] || job.status;
  };

  return <main className="studio">
    <SiteHeader /><LicenseBanner />
    <section className="hero">
      <div className="eyebrow">{t.home.eyebrow}</div>
      <h1>{t.home.title1}<br />{t.home.title2}</h1>
      <p>{t.home.description}</p>
      <form onSubmit={start} className="convert-form"><label htmlFor="youtube-url" className="sr-only">YouTube URL</label><input id="youtube-url" type="url" required placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(event) => {setUrl(event.target.value);setResourceWarning(null);setPendingConvert(null);}} /><button type="submit" disabled={busy || !license.allowed}>{busy ? t.home.checking : t.home.convert} ↗</button></form>
      <VoiceSelect value={voice} onChange={setVoice} />
      {message && <p className="alert" role="alert">{message}</p>}
      {resourceWarning&&<section role="alert" className="alert">
        <h3>{t.home.resourceWarningTitle}</h3>
        <p>{t.home.existingWorkflows.replace("{count}", String(resourceWarning.existing_workflows))}</p>
        <ul>{resourceWarning.reasons.map(reason=><li key={reason}>{tr(reason)}</li>)}</ul>
        <p>{resourceWarning.estimate_basis==='estimated'?tr("Dự toán RAM model tạm tính; chưa có benchmark thật. "):tr("Dự toán theo bộ nhớ model đã đo. ")}{tr("Bạn có thể xếp hàng chờ; workflow vẫn xử lý lần lượt, không ép chạy song song.")}</p>
        <button type="button" disabled={busy||!license.allowed||!pendingConvert} onClick={()=>{if(pendingConvert)void convert(pendingConvert,true);}}>{t.home.queueWait}</button>{' '}
        <button type="button" disabled={busy} onClick={()=>{setResourceWarning(null);setPendingConvert(null);}}>{t.home.dismiss}</button>
      </section>}
      <div className="hero-foot"><span>{t.home.step1}</span><span>{t.home.step2}</span><span>{t.home.step3}</span><span>{t.home.step4}</span></div>
    </section>
    <section className="jobs-section">
      <div className="section-head"><div><span className="eyebrow">{t.home.workspace}</span><h2>{t.home.jobs} <span className="count">{studioJobs.length}</span></h2><Link href="/history">{t.home.completedToHistory}</Link></div><button className="refresh" onClick={() => void refresh()} type="button">↻ {t.home.refresh}</button></div>
      <div className="table-wrap"><table><thead><tr><th>{t.home.thName}</th><th>{t.home.thDuration}</th><th>{t.home.thStatus}</th><th>{t.home.thProgress}</th><th>{t.home.thCreated}</th><th>{t.home.thOutput}</th><th>{t.home.thActions}</th></tr></thead><tbody>
        {studioJobs.map((job) => <tr key={job.id}>
          <td className="name-cell"><strong title={job.name}>{job.name}</strong><small>{tr("Workflow #")}{runNumber(job.workflow_no)}</small></td>
          <td>{duration(job.duration_ms)}</td>
          <td><span className={`status status-${job.status.toLowerCase()}`}><i />{getStatusLabel(job)}</span>{job.error && <small className="error-detail" title={tr(job.error)}>{tr(job.error)}</small>}</td>
          <td><div className="progress-row"><span>{percent(job.progress)}</span><div className="progress-track"><div style={{ width: `${percent(job.progress)}` }} /></div></div>{job.status === "VAD" && job.processed_ms ? <small>{duration(job.processed_ms)} / {duration(job.duration_ms)}</small> : job.chunks_total ? <small>{job.chunks_done || 0}/{job.chunks_total} {t.home.chunksUnit}</small> : null}</td>
          <td>{new Date(job.created_at).toLocaleString(language === "vi" ? "vi-VN" : "en-US")}</td>
          <td className="output-cell"><button type="button" onClick={() => view(selected === job.id ? null : job.id)}>{selected === job.id ? t.home.closeDetails : t.home.details}</button>
            {job.status === "FAILED" && <button type="button" disabled={!license.allowed} onClick={() => void retry(job.id)}>{t.home.retry}</button>}
            {job.status === "COMPLETED" && job.workflow_version !== 2 && <button type="button" disabled={!license.allowed} onClick={() => void retry(job.id)}>{t.home.continueTranslate}</button>}</td>
          <td><WorkflowActions job={job} onChanged={refresh} onNotice={setMessage} canResume={license.allowed}/></td>
        </tr>)}
      </tbody></table>{!studioJobs.length && <div className="empty"><span>◎</span><strong>{t.home.emptyTitle}</strong><p>{t.home.emptyDesc.replace("{history}", "")} <Link href="/history">{tr("History")}</Link>.</p></div>}</div>
      {studioJobs.filter(job => job.id === selected).map(job => <JobDetail key={job.id} job={job} onClose={() => view(null)} />)}
    </section>
    <RulesPanel moderating={jobs.some(job => job.status === "MODERATING")} />
    <footer>{t.home.footer}</footer>
  </main>;
}
