"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import {useEffect,useState} from "react";
import SiteHeader from "@/components/layout/site-header";
import PipelineStatus from "@/components/workflow/pipeline-status";
import VoiceSelect from "@/components/voice/voice-select";
import StepErrors from "@/components/workflow/step-errors";
import {useLicense} from "@/components/license/license-status";
import type {Job,Step} from "@/lib/server/jobs";
import {runNumber} from "@/lib/shared/format";
import {useNotice} from '@/components/common/use-notice';
const stages:Step[]=["DOWNLOAD","TRANSCRIPTION","TRANSLATION","MODERATION","TTS"];
export default function Reprocess(){
  const { tr } = useLanguage();
  const license=useLicense();const [jobs,setJobs]=useState<Job[]>([]),[id,setId]=useState(""),[step,setStep]=useState<Step>("TTS"),[voice,setVoice]=useState(""),[style,setStyle]=useState(""),[busy,setBusy]=useState(false);const [message,setMessage]=useNotice();
  useEffect(()=>{const c=new AbortController();let initial=true;const requested=new URLSearchParams(window.location.search).get("id");const load=()=>fetch("/api/jobs",{cache:"no-store",signal:c.signal}).then(r=>r.json()).then(d=>{setJobs(d.jobs||[]);if(initial&&requested){const found=(d.jobs||[]).find((j:Job)=>j.id===requested);setId(requested);setVoice(found?.selected_voice_id||"");setStyle(found?.selected_voice_style||"default");}initial=false;}).catch(()=>{});void load();const t=setInterval(()=>void load(),3000);return()=>{c.abort();clearInterval(t);};},[]);
  const job=jobs.find(j=>j.id===id),stopped=job&&["COMPLETED","FAILED","CANCELLED","PAUSED","PARTIAL"].includes(job.status);
  async function run(e:React.FormEvent){e.preventDefault();if(!window.confirm(tr('reprocessConfirm',{number:runNumber(job?.workflow_no),step:tr(step)})))return;setBusy(true);try{const r=await fetch(`/api/jobs/${id}/reprocess`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step,voice:voice||undefined,style:style||undefined})});const d=await r.json();setMessage(r.ok?tr("Đã xếp hàng reprocess; các output downstream hiện là STALE."):d.error);}catch{setMessage(tr("Không gửi được reprocess."));}finally{setBusy(false);}}
  return <main className="studio"><SiteHeader/><section className="hero"><h1>{tr("Reprocess workflow")}</h1><p>{tr("Giữ kết quả trước bước được chọn. Tạo lại bước này và toàn bộ bước phía sau với cùng Workflow #.")}</p><form onSubmit={run} className="tool-form"><label>{tr("Workflow")}<select value={id} required onChange={e=>{const found=jobs.find(j=>j.id===e.target.value);setId(e.target.value);setVoice(found?.selected_voice_id||"");setStyle(found?(found.selected_voice_style||"default"):"");}}><option value="">{tr("Chọn workflow")}</option>{jobs.map(j=><option key={j.id} value={j.id}>#{runNumber(j.workflow_no)} · {j.name} · {tr(j.status)}</option>)}</select></label><label>{tr("Restart From")}<select value={step} onChange={e=>setStep(e.target.value as Step)}>{stages.map((s,i)=><option key={s} value={s} disabled={!!job&&stages.slice(0,i).some(p=>job.steps?.[p]?.state!=="COMPLETED")}>{tr(s)}</option>)}</select></label><VoiceSelect value={voice} onChange={setVoice} style={style} onStyleChange={setStyle}/><button disabled={!license.allowed||!stopped||busy}>{tr("Reprocess")}</button></form>{message&&<p className="alert" role="status">{message}</p>}</section>{job&&<><PipelineStatus job={job}/><StepErrors job={job}/><a href={`/history/${job.id}`}>{tr("View outputs →")}</a></>}</main>;
}
