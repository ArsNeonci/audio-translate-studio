"use client";
import { useLanguage } from "@/lib/language-context";
import {useEffect,useState} from "react";
import type {Job,Step} from "@/lib/jobs";
import {elapsed,percent,runNumber} from "@/lib/format";
import {transcriptionView, type TranscriptionStep} from "@/lib/transcription-progress";
type Run=Pick<Job,"id"|"workflow_no"|"steps"|"stages"|"progress"|"started_at"|"run_started_at"|"completed_at"|"total_duration_ms"|"tool_steps"|"transcription_steps"|"chunks_done"|"chunks_total"|"duration_ms"|"processed_ms"|"asr_runtime"|"pause_requested"|"delete_requested"|"storage_scope"> & {status:string};
export default function PipelineStatus({job}:{job:Run;readOnly?:boolean}){
  const { tr } = useLanguage();
  const [clock,setClock]=useState(0);
  useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[]);
  const effective=job.tool_steps||["DOWNLOAD","TRANSCRIPTION","TRANSLATION","MODERATION","TTS"] as Step[];
  const active=!["COMPLETED","FAILED","CANCELLED","PAUSED","PARTIAL","DELETING"].includes(job.status);
  const time=(start?:string|null)=>start&&clock?Math.max(0,clock-Date.parse(start)):0;
  const phases=transcriptionView(job);
  const rows=effective.flatMap<{label:string;item:TranscriptionStep|undefined}>(stage=>stage==='TRANSCRIPTION'?phases.map((item,index)=>({label:`${tr("TRANSCRIPTION")} ${index+1}/4`,item:{...item,output_manifest:index===3?job.steps?.TRANSCRIPTION?.output_manifest:undefined}})): [{label:tr(stage),item:job.steps?.[stage]}]);
  const status=job.delete_requested?tr("ĐANG HỦY VÀ XÓA"):job.pause_requested?tr("ĐANG DỪNG SAU TASK HIỆN TẠI"):['VAD','TRANSCRIBING','MERGING','TRANSCRIPTION_COMPLETED'].includes(job.status)?tr("TRANSCRIPTION"):tr(job.status);
  return <section className="pipeline-status"><h3>#{runNumber(job.workflow_no)} · {status}</h3><p>{tr("Overall:")} {percent(job.progress)} {tr("· Total:")} {elapsed(active&&job.run_started_at?(job.total_duration_ms||0)+time(job.run_started_at):job.total_duration_ms)}</p><small>{tr("overallNote", {count: effective.length})}</small><div className="progress-track">{job.progress!=null&&<div style={{width:`${job.progress}%`}}/>}</div>
    <table><thead><tr><th>{tr("Stage")}</th><th>{tr("Status")}</th><th>{tr("Progress")}</th><th>{tr("Elapsed")}</th><th title={tr("Số lần bắt đầu chạy; 0: chưa chạy, 1: lần đầu, 2: lần thứ hai")}>{tr("Attempt")}</th><th title={tr("Chỉ đếm file kết quả đã xuất, không đếm cache nội bộ")}>{tr("Output")}</th></tr></thead><tbody>{rows.map(({label,item})=>{const value=item?.state==='COMPLETED'?100:item?.progress;return <tr key={label}><td>{label}</td><td>{tr(item?.state||'PENDING')}</td><td>{percent(value)}{item?.state==='RUNNING'&&value==null&&<span role="status" aria-label={tr("Đang xử lý")} className="indeterminate"> ⟳</span>}</td><td>{elapsed(item?.state==='RUNNING'?item.started_at?(item.duration_ms||0)+time(item.started_at):null:item?.duration_ms)}</td><td>{item?.inferred?'—':item?.attempt||0}</td><td>{item?.output_manifest?.filter(f=>f.status==='AVAILABLE').length||0} {tr("files")}{item?.output_manifest?.some(f=>f.status==='STALE')&&` · ${tr('STALE')}`}</td></tr>;})}</tbody></table>
    <small>{tr("Attempt = số lần bắt đầu chạy bước. Output chỉ tính kết quả đã xuất; audio tải về và checkpoint được lưu nội bộ.")}</small>
    {job.steps?.TRANSCRIPTION?.state==='RUNNING'&&job.asr_runtime&&<p role="status">{tr("Auto CPU:")} {job.asr_runtime.state==='WAITING_MEMORY'?tr("ramWaiting", {available: job.asr_runtime.ram_available_gib ?? "—", required: job.asr_runtime.required_available_gib ?? "—"}):job.asr_runtime.state==='CALIBRATING'?tr("Đang đo cấu hình CPU phù hợp…"):`${tr("cpuWorkers", {workers: job.asr_runtime.workers ?? "—", threads: job.asr_runtime.threads ?? "—"})}${job.asr_runtime.throttled?tr(" · Đang giảm tải"):''}`}</p>}
    {phases.some(item=>item.inferred)&&effective.includes('TRANSCRIPTION')&&<p><small>{tr("Phiên cũ: tiến độ được suy ra từ checkpoint; thời gian không có dữ liệu và Attempt từng bước hiển thị —.")}</small></p>}
  </section>;
}
