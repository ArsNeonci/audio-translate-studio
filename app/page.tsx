"use client";
import {useLicense} from "@/components/license/license-status";
import LicenseBanner from "@/components/license/license-status";

import { useCallback, useEffect, useState } from "react";
import type { Job } from "@/lib/server/jobs";
import JobDetail from "@/components/workflow/job-detail";
import RulesPanel from "@/components/rules/rules-panel";
import VoiceSelect from "@/components/voice/voice-select";
import AddressProfileSelect from "@/components/voice/address-profile-select";
import TranslationModeSelect from "@/components/voice/translation-mode-select";
import AutoTtsToggle from "@/components/voice/auto-tts-toggle";
import type {TranslationMode} from "@/lib/shared/translation-modes";
import {addressForStyle} from "@/lib/shared/address-profiles";
import {audioDuration,percent,runNumber} from "@/lib/shared/format";
import SiteHeader from "@/components/layout/site-header";
import Link from 'next/link';
import {useNotice} from '@/components/common/use-notice';
import WorkflowActions from '@/components/workflow/workflow-actions';
import FilePicker from '@/components/common/file-picker';
import { useLanguage } from "@/lib/i18n/language-context";

const duration = audioDuration;
const AUDIO_TYPES=".wav,.mp3,.m4a,.flac,.ogg,.aac,.webm,.mp4";
type ConvertInput={url:string;file?:File;voice?:string;style?:string;address?:string;mode?:TranslationMode;auto?:boolean};
type ResourceWarning={reasons:string[];ram_available_gib:number;required_available_gib:number;cpu_percent:number;existing_workflows:number;estimate_basis:string};

export default function Home() {
  const { language, t , tr} = useLanguage();
  const license = useLicense();
  const [url, setUrl] = useState("");
  // Source of the Chinese audio: a YouTube link, or a file when YouTube refuses the download.
  const [source,setSource]=useState<"link"|"file">("link"),[file,setFile]=useState<File|null>(null);
  const [voice,setVoice]=useState(""),[style,setStyle]=useState(""),[address,setAddress]=useState("");
  const [mode,setMode]=useState<TranslationMode>("normal"),[auto,setAuto]=useState(false);
  const basic=license.edition==="basic";
  const chooseStyle=useCallback((value:string)=>{setStyle(value);setAddress(addressForStyle(value));},[]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useNotice();
  const [selected, setSelected] = useState<string | null>(null);
  const [resourceWarning,setResourceWarning]=useState<ResourceWarning|null>(null);
  const [pendingConvert,setPendingConvert]=useState<ConvertInput|null>(null);
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
    // Genius handles forms of address itself, so none is sent.
    const extra={...(basic?{auto}:{}),...(source==="file"&&file?{file}:{})};
    if(source==="file"&&!file)return;
    const link=source==="file"?"":url;
    await convert(mode==="genius"?{url:link,voice:voice||undefined,style:style||undefined,mode,...extra}:{url:link,voice:voice||undefined,style:style||undefined,address:address||undefined,...extra});
  }

  async function send(input:ConvertInput,queue_only:boolean){
    const {file:upload,...fields}=input;
    if(!upload)return fetch("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...fields,queue_only }) });
    const params=new URLSearchParams({name:upload.name});
    for(const [key,value] of Object.entries(fields))if(key!=="url"&&value!==undefined&&value!==false)params.set(key,value===true?"1":String(value));
    if(queue_only)params.set("queue_only","1");
    return fetch(`/api/jobs?${params}`,{method:"POST",headers:{"Content-Type":upload.type||"application/octet-stream"},body:upload});
  }

  async function convert(input:ConvertInput,queue_only=false){
    if(busy)return;
    setBusy(true); setMessage("");setResourceWarning(null);
    try {
      const response = await send(input,queue_only);
      const data = await response.json();
      if(data.code==='RESOURCE_WARNING'){
        setResourceWarning(data.assessment);setPendingConvert(input);return;
      }
      if (!response.ok) throw new Error(data.error || tr("Không tạo được job."));
      setPendingConvert(null);setUrl("");setFile(null); await refresh();
      setMessage(t.home.queuedNotice);
    } catch (error) { setMessage(error instanceof Error ? tr(error.message) : tr("Không tạo được job.")); }
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
      <div className="source-options source-options-studio" role="radiogroup" aria-label={tr("Nguồn âm thanh")}>{(["link","file"] as const).map(value=><button key={value} type="button" role="radio" aria-checked={source===value} className={`source-chip${source===value?" selected":""}`} onClick={()=>{setSource(value);setResourceWarning(null);setPendingConvert(null);}}>{value==="link"?tr("Link YouTube"):tr("Tệp âm thanh tiếng Trung")}</button>)}</div>
      <form onSubmit={start} className="convert-form">{source==="link"?<><label htmlFor="youtube-url" className="sr-only">YouTube URL</label><input id="youtube-url" type="url" required placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(event) => {setUrl(event.target.value);setResourceWarning(null);setPendingConvert(null);}} /></>:<FilePicker accept={AUDIO_TYPES} file={file} onChange={value=>{setFile(value);setResourceWarning(null);setPendingConvert(null);}} />}<button type="submit" disabled={busy || !license.allowed || (source==="file"&&!file)}>{busy ? t.home.checking : t.home.convert} ↗</button></form>
      {source==="file"&&<p className="source-hint">{tr("Dùng khi YouTube chặn tải: tải audio bằng công cụ khác rồi chọn file ở đây (WAV, MP3, M4A, FLAC, OGG, AAC, WEBM, MP4; tối đa 2 GB). Workflow bỏ qua bước tải YouTube.")}</p>}
      <VoiceSelect value={voice} onChange={setVoice} style={style} onStyleChange={chooseStyle} />
      <TranslationModeSelect value={mode} onChange={setMode} />
      {mode==="normal"&&<AddressProfileSelect value={address} onChange={setAddress} />}
      {basic&&<AutoTtsToggle checked={auto} onChange={setAuto} />}
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
