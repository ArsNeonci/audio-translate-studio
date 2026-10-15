"use client";
import { apiFetch, useNotice } from "@audio/ui";
import { useLanguage } from "@/lib/i18n/language-context";
import {useCallback,useEffect,useState} from "react";
import SiteHeader from "@/components/layout/site-header";
import PipelineStatus from "@/components/workflow/pipeline-status";
import VoiceSelect from "@/components/voice/voice-select";
import AddressProfileSelect from "@/components/voice/address-profile-select";
import CharacterEditor from "@/components/voice/character-editor";
import TranslationModeSelect from "@/components/voice/translation-mode-select";
import type {TranslationMode} from "@/lib/shared/translation-modes";
import {addressForStyle} from "@/lib/shared/address-profiles";
import StepErrors from "@/components/workflow/step-errors";
import {LeaseOfflineNotice,useLicense} from "@/components/license/license-status";
import type {Job,Step} from "@/lib/shared/job-types";
import {runNumber} from "@/lib/shared/format";
import VideoPicker,{emptyVideo,videoFromJob,videoPayload,videoReady,type VideoChoice} from "@/components/video/video-picker";
import SubtitleOptions,{defaultSubtitle,subtitleFromJob,subtitleValid,type SubtitleSettings} from "@/components/video/subtitle-options";
import {STEPS} from "@/lib/shared/job-types";
const stages:Step[]=["DOWNLOAD","TRANSCRIPTION","TRANSLATION","MODERATION","TTS","SUBTITLE","VIDEO","BURN"];
export default function Reprocess(){
  const { tr } = useLanguage();
  const license=useLicense();const [jobs,setJobs]=useState<Job[]>([]),[id,setId]=useState(""),[step,setStep]=useState<Step>("TTS"),[voice,setVoice]=useState(""),[style,setStyle]=useState(""),[address,setAddress]=useState(""),[mode,setMode]=useState<TranslationMode>("normal"),[busy,setBusy]=useState(false);const [message,setMessage]=useNotice();
  const [video,setVideo]=useState<VideoChoice>(emptyVideo),[subtitle,setSubtitle]=useState<SubtitleSettings>(defaultSubtitle),[burnNow,setBurnNow]=useState(false);
  const pick=useCallback((found?:Job)=>{setVideo(videoFromJob(found?.video));setBurnNow(false);setSubtitle(subtitleFromJob(found?.subtitle));setVoice(found?.selected_voice_id||"");setStyle(found?(found.selected_voice_style||"default"):"");setAddress(found?(found.selected_address_profile||"neutral"):"");setMode(found?.translation_mode==="genius"?"genius":"normal");},[]);
  useEffect(()=>{const c=new AbortController();let initial=true;const requested=new URLSearchParams(window.location.search).get("id");const load=()=>apiFetch("/api/jobs",{cache:"no-store",signal:c.signal}).then(r=>r.json()).then(d=>{setJobs(d.jobs||[]);if(initial&&requested){setId(requested);pick((d.jobs||[]).find((j:Job)=>j.id===requested));}initial=false;}).catch(()=>{});void load();const t=setInterval(()=>void load(),3000);return()=>{c.abort();clearInterval(t);};},[pick]);
  const job=jobs.find(j=>j.id===id),stopped=job&&["COMPLETED","FAILED","CANCELLED","PAUSED","PARTIAL"].includes(job.status);
  const translating=stages.indexOf(step)<=stages.indexOf("TRANSLATION");
  const canBurn=!!job?.video&&job.steps?.VIDEO?.state==="COMPLETED";
  async function run(e:React.FormEvent){e.preventDefault();if(!window.confirm(tr('reprocessConfirm',{number:runNumber(job?.workflow_no),step:tr(step)})))return;setBusy(true);try{const genius=(translating?mode:job?.translation_mode==="genius"?"genius":"normal")==="genius";const body=step==="VIDEO"?{step,video:videoPayload(video)}:step==="SUBTITLE"?{step,subtitle,...(burnNow&&canBurn?{burn:true}:{})}:step==="BURN"?{step,subtitle}:{step,voice:voice||undefined,style:style||undefined,address:genius?undefined:address||undefined,mode:translating?mode:undefined,...(job?.video&&video.files.length?{video:videoPayload(video)}:{})};const r=await apiFetch(`/api/jobs/${id}/reprocess`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const d=await r.json();setMessage(r.ok?tr("Đã xếp hàng reprocess; các output downstream hiện là STALE."):tr(d.error));}catch{setMessage(tr("Không gửi được reprocess."));}finally{setBusy(false);}}
  const genius=(translating?mode:job?.translation_mode==="genius"?"genius":"normal")==="genius";
  return <main className="studio"><SiteHeader/><section className="hero"><h1>{tr("Reprocess workflow")}</h1><LeaseOfflineNotice license={license} onChange={license.setLicense}/><p>{tr("Giữ kết quả trước bước được chọn. Tạo lại bước này và toàn bộ bước phía sau với cùng Workflow #.")}</p><form onSubmit={run} className="tool-form"><label>{tr("Workflow")}<select value={id} required onChange={e=>{setId(e.target.value);pick(jobs.find(j=>j.id===e.target.value));}}><option value="">{tr("Chọn workflow")}</option>{jobs.map(j=><option key={j.id} value={j.id}>#{runNumber(j.workflow_no)} · {j.name} · {tr(j.status)}</option>)}</select></label><label>{tr("Restart From")}<select value={step} onChange={e=>setStep(e.target.value as Step)}>{stages.map(s=>{const i=stages.indexOf(s);return <option key={s} value={s} disabled={!!job&&(stages.slice(0,i).some(p=>(STEPS.includes(p)||!!job.steps?.[p])&&job.steps?.[p]?.state!=="COMPLETED")||(s==="BURN"&&!job.video))}>{tr(s)}{s==="VIDEO"&&!job?.video?` (${tr("videoAdd")})`:s==="SUBTITLE"&&!job?.subtitle?` (${tr("subtitleAdd")})`:s==="BURN"&&job?.video&&!job.video.burn?` (${tr("burnAdd")})`:""}</option>;})}</select></label>{step==="VIDEO"?<VideoPicker value={video} onChange={setVideo} voiceJob={id||null} disabled={busy}/>:step==="SUBTITLE"||step==="BURN"?<><SubtitleOptions value={subtitle} onChange={setSubtitle} disabled={busy}/>{step==="SUBTITLE"&&canBurn&&<label className="auto-tts-toggle"><input type="checkbox" checked={burnNow} disabled={busy} onChange={e=>setBurnNow(e.target.checked)}/><span>{tr("burnLabel")}</span><small>{tr("burnHelp")}</small></label>}{step==="BURN"&&<p className="alert" role="note">{tr("burnStageNote")}</p>}</>:<>{translating&&<TranslationModeSelect value={mode} onChange={setMode}/>}<VoiceSelect value={voice} onChange={setVoice} style={style} onStyleChange={value=>{if(value!==style&&style)setAddress(addressForStyle(value));setStyle(value);}}/>{!genius&&<AddressProfileSelect value={address} onChange={setAddress}/>}</>}<button disabled={!license.allowed||!stopped||busy||(step==="VIDEO"&&!videoReady(video))||((step==="SUBTITLE"||step==="BURN")&&!subtitleValid(subtitle))}>{tr("Reprocess")}</button></form>{message&&<p className="alert" role="status">{message}</p>}</section>{job&&<>{!genius&&<CharacterEditor key={job.id} jobId={job.id}/>}<PipelineStatus job={job}/><StepErrors job={job}/><a href={`/history/view?id=${job.id}`}>{tr("View outputs →")}</a></>}</main>;
}
