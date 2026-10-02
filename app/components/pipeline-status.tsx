"use client";
import {useEffect,useState} from "react";
import type {Job,Step} from "@/lib/jobs";
import {elapsed,percent,runNumber} from "@/lib/format";
import {transcriptionView, type TranscriptionStep} from "@/lib/transcription-progress";
type Run=Pick<Job,"id"|"workflow_no"|"steps"|"stages"|"progress"|"started_at"|"run_started_at"|"completed_at"|"total_duration_ms"|"tool_steps"|"transcription_steps"|"chunks_done"|"chunks_total"|"duration_ms"|"processed_ms"|"asr_runtime"|"pause_requested"|"delete_requested"|"storage_scope"> & {status:string};
export default function PipelineStatus({job}:{job:Run;readOnly?:boolean}){
  const [clock,setClock]=useState(0);
  useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[]);
  const effective=job.tool_steps||["DOWNLOAD","TRANSCRIPTION","TRANSLATION","MODERATION","TTS"] as Step[];
  const active=!["COMPLETED","FAILED","CANCELLED","PAUSED","PARTIAL","DELETING"].includes(job.status);
  const time=(start?:string|null)=>start&&clock?Math.max(0,clock-Date.parse(start)):0;
  const phases=transcriptionView(job);
  const rows=effective.flatMap<{label:string;item:TranscriptionStep|undefined}>(stage=>stage==='TRANSCRIPTION'?phases.map((item,index)=>({label:`TRANSCRIPTION ${index+1}/4`,item:{...item,output_manifest:index===3?job.steps?.TRANSCRIPTION?.output_manifest:undefined}})): [{label:stage,item:job.steps?.[stage]}]);
  const status=job.delete_requested?'ĐANG HỦY VÀ XÓA':job.pause_requested?'ĐANG DỪNG SAU TASK HIỆN TẠI':['VAD','TRANSCRIBING','MERGING','TRANSCRIPTION_COMPLETED'].includes(job.status)?'TRANSCRIPTION':job.status;
  return <section className="pipeline-status"><h3>#{runNumber(job.workflow_no)} · {status}</h3><p>Overall: {percent(job.progress)} · Total: {elapsed(active&&job.run_started_at?(job.total_duration_ms||0)+time(job.run_started_at):job.total_duration_ms)}</p><small>Overall vẫn dùng trung bình đều của {effective.length} stage chính; công việc chưa xác định tổng hiển thị —.</small><div className="progress-track">{job.progress!=null&&<div style={{width:`${job.progress}%`}}/>}</div>
    <table><thead><tr><th>Stage</th><th>Status</th><th>Progress</th><th>Elapsed</th><th title="Số lần bắt đầu chạy; 0: chưa chạy, 1: lần đầu, 2: lần thứ hai">Attempt</th><th title="Chỉ đếm file kết quả đã xuất, không đếm cache nội bộ">Output</th></tr></thead><tbody>{rows.map(({label,item})=>{const value=item?.state==='COMPLETED'?100:item?.progress;return <tr key={label}><td>{label}</td><td>{item?.state||'PENDING'}</td><td>{percent(value)}{item?.state==='RUNNING'&&value==null&&<span role="status" aria-label="Đang xử lý" className="indeterminate"> ⟳</span>}</td><td>{elapsed(item?.state==='RUNNING'?item.started_at?(item.duration_ms||0)+time(item.started_at):null:item?.duration_ms)}</td><td>{item?.inferred?'—':item?.attempt||0}</td><td>{item?.output_manifest?.filter(f=>f.status==='AVAILABLE').length||0} files{item?.output_manifest?.some(f=>f.status==='STALE')&&' · STALE'}</td></tr>;})}</tbody></table>
    <small>Attempt = số lần bắt đầu chạy bước. Output chỉ tính kết quả đã xuất; audio tải về và checkpoint được lưu nội bộ.</small>
    {job.steps?.TRANSCRIPTION?.state==='RUNNING'&&job.asr_runtime&&<p role="status">Auto CPU: {job.asr_runtime.state==='WAITING_MEMORY'?`Đang chờ RAM — còn ${job.asr_runtime.ram_available_gib} GB, cần khoảng ${job.asr_runtime.required_available_gib} GB trống.`:job.asr_runtime.state==='CALIBRATING'?'Đang đo cấu hình CPU phù hợp…':`${job.asr_runtime.workers} worker × ${job.asr_runtime.threads} luồng${job.asr_runtime.throttled?' · Đang giảm tải':''}`}</p>}
    {phases.some(item=>item.inferred)&&effective.includes('TRANSCRIPTION')&&<p><small>Phiên cũ: tiến độ được suy ra từ checkpoint; thời gian không có dữ liệu và Attempt từng bước hiển thị —.</small></p>}
  </section>;
}
