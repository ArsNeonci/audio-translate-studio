"use client";
import {useEffect,useState} from "react";
import SiteHeader from "@/app/components/site-header";
import PipelineStatus from "@/app/components/pipeline-status";
import VoiceSelect from "@/app/components/voice-select";
import StepErrors from "@/app/components/step-errors";
import {useLicense} from "@/app/components/license-status";
import type {Job,Step} from "@/lib/jobs";
import {runNumber} from "@/lib/format";
import {useNotice} from '@/app/components/use-notice';
const stages:Step[]=["DOWNLOAD","TRANSCRIPTION","TRANSLATION","MODERATION","TTS"];
export default function Reprocess(){
  const license=useLicense();const [jobs,setJobs]=useState<Job[]>([]),[id,setId]=useState(""),[step,setStep]=useState<Step>("TTS"),[voice,setVoice]=useState(""),[busy,setBusy]=useState(false);const [message,setMessage]=useNotice();
  useEffect(()=>{const c=new AbortController();let initial=true;const requested=new URLSearchParams(window.location.search).get("id");const load=()=>fetch("/api/jobs",{cache:"no-store",signal:c.signal}).then(r=>r.json()).then(d=>{setJobs(d.jobs||[]);if(initial&&requested){setId(requested);setVoice((d.jobs||[]).find((j:Job)=>j.id===requested)?.selected_voice_id||"");}initial=false;}).catch(()=>{});void load();const t=setInterval(()=>void load(),3000);return()=>{c.abort();clearInterval(t);};},[]);
  const job=jobs.find(j=>j.id===id),stopped=job&&["COMPLETED","FAILED","CANCELLED","PAUSED","PARTIAL"].includes(job.status);
  async function run(e:React.FormEvent){e.preventDefault();setBusy(true);try{const r=await fetch(`/api/jobs/${id}/reprocess`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step,voice:voice||undefined})});const d=await r.json();setMessage(r.ok?"Đã xếp hàng reprocess; các output downstream hiện là STALE.":d.error);}catch{setMessage("Không gửi được reprocess.");}finally{setBusy(false);}}
  return <main className="studio"><SiteHeader/><section className="hero"><h1>Reprocess workflow</h1><p>Giữ kết quả trước bước được chọn. Tạo lại bước này và toàn bộ bước phía sau với cùng Workflow #.</p><form onSubmit={run} className="tool-form"><label>Workflow<select value={id} required onChange={e=>{setId(e.target.value);setVoice(jobs.find(j=>j.id===e.target.value)?.selected_voice_id||"");}}><option value="">Chọn workflow</option>{jobs.map(j=><option key={j.id} value={j.id}>#{runNumber(j.workflow_no)} · {j.name} · {j.status}</option>)}</select></label><label>Restart From<select value={step} onChange={e=>setStep(e.target.value as Step)}>{stages.map((s,i)=><option key={s} disabled={!!job&&stages.slice(0,i).some(p=>job.steps?.[p]?.state!=="COMPLETED")}>{s}</option>)}</select></label><VoiceSelect value={voice} onChange={setVoice}/><button disabled={!license.allowed||!stopped||busy}>Reprocess</button></form>{message&&<p className="alert" role="status">{message}</p>}</section>{job&&<><PipelineStatus job={job}/><StepErrors job={job}/><a href={`/history/${job.id}`}>View outputs →</a></>}</main>;
}
