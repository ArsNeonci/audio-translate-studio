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

const labels: Record<Job["status"], string> = {
  CANCELLED:"Đã dừng (phiên cũ)",PAUSED:"Đã dừng tạm",PARTIAL:"Một phần",DELETING:"Đang xóa",
  QUEUED: "Đang chờ", DOWNLOADING: "Đang tải audio", VAD: "Đang tách lời nói",
  TRANSCRIBING: "Đang nhận dạng", MERGING: "Đang ghép bản chép", COMPLETED: "Hoàn tất", FAILED: "Lỗi",
  TRANSCRIPTION_COMPLETED: "Đã chép tiếng Trung", TRANSLATING: "Đang dịch tiếng Việt", TRANSLATION_COMPLETED: "Đã dịch",
  MODERATING: "Đang thay thế từ", MODERATION_COMPLETED: "Đã duyệt bản dịch", TTS_GENERATING: "Đang tạo giọng Việt",
};
const duration = (ms: number) => ms ? `${Math.floor(ms / 3600000)}h ${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}m` : "—";
type ResourceWarning={reasons:string[];ram_available_gib:number;required_available_gib:number;cpu_percent:number;existing_workflows:number;estimate_basis:string};

export default function Home() {
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
      if (!response.ok) throw new Error("Không tải được danh sách job.");
      setJobs((await response.json()).jobs);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Lỗi kết nối."); }
  }, [setMessage]);

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
      if (!response.ok) throw new Error(data.error || "Không tạo được job.");
      setPendingConvert(null);setUrl(""); await refresh();
      setMessage('Đã xếp hàng workflow. Các workflow được xử lý lần lượt; Auto sẽ chờ nếu chưa đủ RAM.');
    } catch (error) { setMessage(error instanceof Error ? error.message : "Không tạo được job."); }
    finally { setBusy(false); }
  }

  async function retry(id: string) {
    if(!window.confirm('Chạy lại giai đoạn lỗi? Chỉ dữ liệu của giai đoạn này sẽ bị xóa; các bước trước được giữ nguyên.'))return;
    setMessage("");
    try {
      const response = await fetch(`/api/jobs/${id}/retry`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không retry được job.");
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Không retry được job."); }
  }

  function view(id: string | null) {
    setSelected(id);
    if (id) localStorage.setItem("audio-studio-job", id);
    else localStorage.removeItem("audio-studio-job");
  }

  return <main className="studio">
    <SiteHeader /><LicenseBanner />
    <section className="hero">
      <div className="eyebrow">TIẾNG TRUNG → TIẾNG VIỆT</div>
      <h1>Tạo Audio Việt Nam<br />từ Video Audio Trung Quốc</h1>
      <p>Chép lời, dịch tiếng Việt, thay thế từ theo rules của bạn và tạo giọng đọc. Theo dõi từng bước và tải kết quả ngay trong Studio.</p>
      <form onSubmit={start} className="convert-form"><label htmlFor="youtube-url" className="sr-only">YouTube URL</label><input id="youtube-url" type="url" required placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(event) => {setUrl(event.target.value);setResourceWarning(null);setPendingConvert(null);}} /><button type="submit" disabled={busy || !license.allowed}>{busy ? "Đang kiểm tra…" : "Convert"} ↗</button></form>
      <VoiceSelect value={voice} onChange={setVoice} />
      {message && <p className="alert" role="alert">{message}</p>}
      {resourceWarning&&<section role="alert" className="alert">
        <h3>Chưa đủ tài nguyên dự phòng để chạy thêm cùng lúc</h3>
        <p>Có {resourceWarning.existing_workflows} workflow đang chạy hoặc chờ. Bộ kiểm tra không khởi động model.</p>
        <ul>{resourceWarning.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>
        <p>{resourceWarning.estimate_basis==='estimated'?'Dự toán RAM model tạm tính; chưa có benchmark thật. ':'Dự toán theo bộ nhớ model đã đo. '}Bạn có thể xếp hàng chờ; workflow vẫn xử lý lần lượt, không ép chạy song song.</p>
        <button type="button" disabled={busy||!license.allowed||!pendingConvert} onClick={()=>{if(pendingConvert)void convert(pendingConvert,true);}}>Xếp hàng chờ</button>{' '}
        <button type="button" disabled={busy} onClick={()=>{setResourceWarning(null);setPendingConvert(null);}}>Để sau</button>
      </section>}
      <div className="hero-foot"><span>01 · Transcription</span><span>02 · Translation</span><span>03 · Moderation</span><span>04 · Vietnamese voice</span></div>
    </section>
    <section className="jobs-section">
      <div className="section-head"><div><span className="eyebrow">WORKSPACE</span><h2>Jobs <span className="count">{studioJobs.length}</span></h2><Link href="/history">Workflow hoàn tất → Lịch sử</Link></div><button className="refresh" onClick={() => void refresh()} type="button">↻ Làm mới</button></div>
      <div className="table-wrap"><table><thead><tr><th>Name</th><th>Duration</th><th>Status</th><th>Progress</th><th>Created</th><th>Output</th><th>Thao tác</th></tr></thead><tbody>
        {studioJobs.map((job) => <tr key={job.id}>
          <td className="name-cell"><strong title={job.name}>{job.name}</strong><small>Workflow #{runNumber(job.workflow_no)}</small></td>
          <td>{duration(job.duration_ms)}</td>
          <td><span className={`status status-${job.status.toLowerCase()}`}><i />{job.delete_requested?'Đang hủy và xóa':job.pause_requested?'Đang dừng sau task hiện tại':labels[job.status]}</span>{job.error && <small className="error-detail" title={job.error}>{job.error}</small>}</td>
          <td><div className="progress-row"><span>{percent(job.progress)}</span><div className="progress-track"><div style={{ width: `${percent(job.progress)}` }} /></div></div>{job.status === "VAD" && job.processed_ms ? <small>{duration(job.processed_ms)} / {duration(job.duration_ms)}</small> : job.chunks_total ? <small>{job.chunks_done || 0}/{job.chunks_total} đoạn</small> : null}</td>
          <td>{new Date(job.created_at).toLocaleString("vi-VN")}</td>
          <td className="output-cell"><button type="button" onClick={() => view(selected === job.id ? null : job.id)}>{selected === job.id ? "Đóng chi tiết" : "Chi tiết"}</button>
            {job.status === "FAILED" && <button type="button" disabled={!license.allowed} onClick={() => void retry(job.id)}>Thử lại ↻</button>}
            {job.status === "COMPLETED" && job.workflow_version !== 2 && <button type="button" disabled={!license.allowed} onClick={() => void retry(job.id)}>Tiếp tục dịch và đọc →</button>}</td>
          <td><WorkflowActions job={job} onChanged={refresh} onNotice={setMessage} canResume={license.allowed}/></td>
        </tr>)}
      </tbody></table>{!studioJobs.length && <div className="empty"><span>◎</span><strong>Không có workflow đang xử lý</strong><p>Workflow hoàn tất được lưu trong <Link href="/history">Lịch sử</Link>. Nhập URL YouTube để bắt đầu.</p></div>}</div>
      {studioJobs.filter(job => job.id === selected).map(job => <JobDetail key={job.id} job={job} onClose={() => view(null)} />)}
    </section>
    <RulesPanel moderating={jobs.some(job => job.status === "MODERATING")} />
    <footer>Audio Studio <span>·</span> Chinese to Vietnamese</footer>
  </main>;
}
