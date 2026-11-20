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
import ManualTranslationToggle from "@/components/voice/manual-translation-toggle";
import type {TranslationMode} from "@/lib/shared/translation-modes";
import {addressForStyle} from "@/lib/shared/address-profiles";
import StepErrors from "@/components/workflow/step-errors";
import {LeaseOfflineNotice,useLicense} from "@/components/license/license-status";
import {runSteps,type Job,type Step} from "@/lib/shared/job-types";
import {runNumber} from "@/lib/shared/format";
import VideoPicker,{emptyVideo,videoFromJob,videoPayload,videoReady,type VideoChoice} from "@/components/video/video-picker";
import SubtitleOptions,{defaultSubtitle,subtitleFromJob,subtitleValid,type SubtitleSettings} from "@/components/video/subtitle-options";
import {STEPS} from "@/lib/shared/job-types";
import FormSection,{FormStack} from "@/components/common/form-section";
import ImportPanel,{isImportStep,noImport,type ImportChoice} from "@/components/workflow/import-panel";
const stages:Step[]=["DOWNLOAD","TRANSCRIPTION","TRANSLATION","MODERATION","TTS","SUBTITLE","VIDEO","BURN"];
const at=(s:Step)=>stages.indexOf(s);
/** Reprocess: the same cards as the Studio, in the same order (voice, translation, subtitles, video), but only those of the chosen stage and the stages
 *  that run again after it; the stages before it keep their results, so their settings are not shown. Every card starts from the run's saved settings. */
export default function Reprocess(){
  const { tr } = useLanguage();
  const license=useLicense();const [jobs,setJobs]=useState<Job[]>([]),[id,setId]=useState(""),[step,setStep]=useState<Step>("TTS"),[voice,setVoice]=useState(""),[style,setStyle]=useState(""),[address,setAddress]=useState(""),[mode,setMode]=useState<TranslationMode>("normal"),[busy,setBusy]=useState(false);const [message,setMessage]=useNotice();
  const [video,setVideo]=useState<VideoChoice>(emptyVideo),[subtitle,setSubtitle]=useState<SubtitleSettings>(defaultSubtitle),[burnNow,setBurnNow]=useState(false),[manual,setManual]=useState(false),[burnUltra,setBurnUltra]=useState(false);
  const [imp,setImp]=useState<ImportChoice>(noImport);   // the file this stage starts from, when the person loads one
  const pick=useCallback((found?:Job)=>{setImp(noImport());setVideo(videoFromJob(found?.video));setBurnNow(false);setManual(!!found?.manual_translation);setBurnUltra(!!found?.burn_ultra);setSubtitle(subtitleFromJob(found?.subtitle));setVoice(found?.selected_voice_id||"");setStyle(found?(found.selected_voice_style||"default"):"");setAddress(found?(found.selected_address_profile||"neutral"):"");setMode(found?.translation_mode==="genius"?"genius":"normal");},[]);
  useEffect(()=>{const c=new AbortController();let initial=true;const requested=new URLSearchParams(window.location.search).get("id");const load=()=>apiFetch("/api/jobs",{cache:"no-store",signal:c.signal}).then(r=>r.json()).then(d=>{setJobs(d.jobs||[]);if(initial&&requested){setId(requested);pick((d.jobs||[]).find((j:Job)=>j.id===requested));const wanted=new URLSearchParams(window.location.search).get("step");if(wanted&&stages.includes(wanted as Step)){setStep(wanted as Step);if(isImportStep(wanted))setImp(noImport("file"));}}initial=false;}).catch(()=>{});void load();const t=setInterval(()=>void load(),3000);return()=>{c.abort();clearInterval(t);};},[pick]);
  const job=jobs.find(j=>j.id===id),stopped=job&&["COMPLETED","FAILED","CANCELLED","PAUSED","PARTIAL","AWAITING_TRANSLATION"].includes(job.status);
  const ultraRun=!!job?.video?.ultra;   // Ultra fast: the merge draws the subtitles itself, the run has no BURN stage
  const canBurn=!!job?.video&&job.steps?.VIDEO?.state==="COMPLETED";
  const loaded=isImportStep(step)&&imp.mode==="file"&&!!imp.importId;
  const importPanel=!!job&&!job.tool_steps&&isImportStep(step);
  const needsFile=!!job&&isImportStep(step)&&imp.mode==="file";
  // Which cards this stage needs: its own and those of every stage that runs again after it.
  const translating=at(step)<=at("TRANSLATION");
  const showManual=translating&&!job?.tool_steps;
  const byHand=showManual?manual:(imp.mode==="file"&&(step==="MODERATION"||step==="TTS"))||!!job?.manual_translation;   // the translation is the person's own
  const genius=!byHand&&(translating?mode:job?.translation_mode==="genius"?"genius":"normal")==="genius";
  const showMode=translating&&!byHand;
  const showAddress=at(step)<=at("MODERATION")&&!byHand&&!genius;   // forms of address are applied in Moderation: from Voice on they cannot change
  const showVoice=at(step)<=at("TTS");
  const showSubtitle=(at(step)<=at("TTS")&&!!job?.subtitle)||step==="SUBTITLE"||step==="BURN"||(step==="VIDEO"&&video.burn);
  const showVideo=at(step)<=at("VIDEO")&&!job?.tool_steps;
  const savedVideo=job?.video?JSON.stringify(videoPayload(videoFromJob(job.video))):"";
  const chosenVideo=video.files.length?JSON.stringify(videoPayload(video)):"";
  const dropping=showVideo&&step!=="VIDEO"&&!!job?.video&&!video.files.length;   // every clip removed: the run loses its Video merge
  // The stages that will run, as the worker will order them (worker core/errors.py effective_steps and manage.reprocess).
  const projectedVideo=step==="SUBTITLE"?(job?.video?{...job.video,burn:!!job.video.burn||(burnNow&&canBurn)}:undefined):showVideo?(video.files.length?{burn:video.burn,ultra:!!video.ultra}:undefined):job?.video||undefined;
  const projected=job?runSteps({...job,manual_translation:showManual?manual:job.manual_translation,video:projectedVideo,subtitle:job.subtitle||(showSubtitle?subtitle:undefined)}):[];
  const from:Step=step==="TRANSLATION"&&showManual&&manual&&!loaded?"SPLIT":step==="BURN"&&ultraRun?"VIDEO":step;
  let willRun=projected.includes(from)?projected.slice(projected.indexOf(from)):[from];
  if(step==="SUBTITLE")willRun=willRun.filter(s=>s==="SUBTITLE"||(burnNow&&canBurn&&(s==="BURN"||(s==="VIDEO"&&ultraRun))));
  async function run(e:React.FormEvent){e.preventDefault();if(!window.confirm(imp.mode==='file'&&isImportStep(step)?tr('importConfirm',{name:imp.name,number:runNumber(job?.workflow_no),step:tr(step)}):tr('reprocessConfirm',{number:runNumber(job?.workflow_no),step:tr(step)})))return;setBusy(true);try{
    const body:Record<string,unknown>={step};
    if(loaded)body.import_id=imp.importId;
    if(showVoice){body.voice=voice||undefined;body.style=style||undefined;}
    if(showManual&&manual!==!!job?.manual_translation)body.manual=manual;
    if(showMode&&!loaded)body.mode=mode;
    if(showAddress)body.address=address||undefined;
    if(showSubtitle)body.subtitle=subtitle;
    if(step==="SUBTITLE"&&burnNow&&canBurn)body.burn=true;
    if(step==="BURN"&&!ultraRun&&burnUltra!==!!job?.burn_ultra)body.ultra=burnUltra;
    if(step==="VIDEO")body.video=videoPayload(video);
    else if(showVideo&&chosenVideo!==savedVideo){if(chosenVideo)body.video=videoPayload(video);else if(dropping)body.drop_video=true;}   // unchanged videos are not sent (nor checked again)
    const r=await apiFetch(`/api/jobs/${id}/reprocess`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const d=await r.json();setMessage(r.ok?tr("Đã xếp hàng reprocess; các output downstream hiện là STALE."):tr(d.error));if(r.ok)setImp(noImport());}catch{setMessage(tr("Không gửi được reprocess."));}finally{setBusy(false);}}
  let n=importPanel?2:1;
  const next=()=>++n;
  const voiceCard=showVoice&&<FormSection step={next()} title={tr("fkVoice")} description={tr("fkVoiceDesc")}><VoiceSelect value={voice} onChange={setVoice} style={style} onStyleChange={value=>{if(value!==style&&style&&showAddress)setAddress(addressForStyle(value));setStyle(value);}}/></FormSection>;
  const translateCard=(showManual||showMode||showAddress)&&<FormSection step={next()} title={tr("fkTranslate")} description={tr("fkTranslateDesc")}>{showManual&&<ManualTranslationToggle value={manual} onChange={setManual} disabled={busy}/>}{showMode&&<TranslationModeSelect value={mode} onChange={setMode}/>}{showAddress&&<AddressProfileSelect value={address} onChange={setAddress}/>}</FormSection>;
  const subtitleCard=showSubtitle&&<FormSection step={next()} title={tr("fkSubtitle")} description={tr("fkSubtitleDesc")}><SubtitleOptions value={subtitle} onChange={setSubtitle} disabled={busy}/>
    {step==="SUBTITLE"&&canBurn&&<label className="auto-tts-toggle"><input type="checkbox" checked={burnNow} disabled={busy} onChange={e=>setBurnNow(e.target.checked)}/><span>{tr("burnLabel")}</span><small>{tr(ultraRun?"burnHelpUltra":"burnHelp")}</small></label>}
    {step==="BURN"&&<><p className="alert" role="note">{tr("burnStageNote")}</p><label className="auto-tts-toggle"><input type="checkbox" checked={burnUltra} disabled={busy} onChange={e=>setBurnUltra(e.target.checked)}/><span>{tr("burnUltraLabel")}</span><small>{tr("burnUltraHelp")}</small></label></>}</FormSection>;
  const videoCard=showVideo&&<FormSection step={next()} title={tr("fkVideo")} description={tr("fkVideoDesc")}><VideoPicker value={video} onChange={setVideo} voiceJob={id||null} disabled={busy}/>{dropping&&<p className="alert" role="note">{tr("videoDropNote")}</p>}</FormSection>;
  return <main className="studio"><SiteHeader/><section className="hero form-kit"><h1>{tr("Reprocess workflow")}</h1><LeaseOfflineNotice license={license} onChange={license.setLicense}/><form onSubmit={run} className="tool-form"><FormStack>
    <FormSection step={1} title={tr("fkReprocessPick")} description={tr("fkReprocessPickDesc")}>
      <div className="fsec-fields"><label>{tr("Workflow")}<select value={id} required onChange={e=>{setId(e.target.value);pick(jobs.find(j=>j.id===e.target.value));}}><option value="">{tr("Chọn workflow")}</option>{jobs.map(j=><option key={j.id} value={j.id}>#{runNumber(j.workflow_no)} · {j.name} · {tr(j.status)}</option>)}</select></label><label>{tr("Restart From")}<select value={step} onChange={e=>{setStep(e.target.value as Step);setImp(isImportStep(e.target.value)&&job&&!job.tool_steps&&!stages.slice(0,stages.indexOf(e.target.value as Step)).every(p=>!(STEPS.includes(p)||!!job.steps?.[p])||job.steps?.[p]?.state==="COMPLETED")?noImport("file"):noImport());}}>{stages.filter(s=>!(s==="BURN"&&ultraRun)).map(s=>{const i=stages.indexOf(s);return <option key={s} value={s} disabled={!!job&&((!(isImportStep(s)&&!job.tool_steps)&&stages.slice(0,i).some(p=>(STEPS.includes(p)||!!job.steps?.[p])&&job.steps?.[p]?.state!=="COMPLETED"))||(s==="BURN"&&!job.video))}>{tr(s)}{s==="VIDEO"&&!job?.video?` (${tr("videoAdd")})`:s==="SUBTITLE"&&!job?.subtitle?` (${tr("subtitleAdd")})`:s==="BURN"&&job?.video&&!job.video.burn?` (${tr("burnAdd")})`:""}</option>;})}</select></label></div>
      {job&&step==="DOWNLOAD"&&<small>{tr("reprocessSource",{source:job.url||job.name})}</small>}
    </FormSection>
    {importPanel&&<ImportPanel key={`${id}-${step}`} job={job} step={step} value={imp} onChange={setImp} disabled={busy} stepNo={2}/>}
    {voiceCard}{translateCard}{subtitleCard}{videoCard}
    {job&&<p className="video-estimate" role="status">{tr("reprocessWillRun",{steps:willRun.map(s=>tr(s)).join(" → ")})}</p>}
    <div className="fk-submit"><button className="action-button" disabled={!license.allowed||!stopped||busy||(needsFile&&!imp.importId)||(step==="VIDEO"&&!videoReady(video))||(showVideo&&video.files.length>0&&!videoReady(video))||(showSubtitle&&!subtitleValid(subtitle))}>{tr("Reprocess")}</button>{!!job&&!stopped&&<small>{tr("fkRunWorkflowNote")}</small>}</div>
  </FormStack></form>{message&&<p className="alert" role="status">{message}</p>}</section>{job&&<>{!genius&&!byHand&&<CharacterEditor key={job.id} jobId={job.id}/>}<PipelineStatus job={job}/><StepErrors job={job}/><a href={`/history/view?id=${job.id}`}>{tr("View outputs →")}</a></>}</main>;
}
