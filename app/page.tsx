"use client";

import { useCallback, useEffect, useState } from "react";
import type { Job } from "@/lib/jobs";

const labels: Record<Job["status"], string> = {
  QUEUED: "Đang chờ", DOWNLOADING: "Đang tải audio", VAD: "Đang tách lời nói",
  TRANSCRIBING: "Đang nhận dạng", MERGING: "Đang ghép bản chép", COMPLETED: "Hoàn tất", FAILED: "Lỗi",
};
const duration = (ms: number) => ms ? `${Math.floor(ms / 3600000)}h ${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}m` : "—";

export default function Home() {
  const [url, setUrl] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/jobs", { cache: "no-store" });
      if (!response.ok) throw new Error("Không tải được danh sách job.");
      setJobs((await response.json()).jobs);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Lỗi kết nối."); }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);

  async function start(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không tạo được job.");
      setUrl(""); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Không tạo được job."); }
    finally { setBusy(false); }
  }

  async function retry(id: string) {
    setMessage("");
    try {
      const response = await fetch(`/api/jobs/${id}/retry`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không retry được job.");
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Không retry được job."); }
  }

  async function view(id: string) {
    if (selected === id) { setSelected(null); return; }
    setSelected(id); setTranscript("Đang tải transcript…");
    try {
      const response = await fetch(`/api/jobs/${id}/transcript`, { cache: "no-store" });
      if (!response.ok) throw new Error("Không đọc được transcript.");
      setTranscript(await response.text());
    } catch (error) { setTranscript(error instanceof Error ? error.message : "Lỗi tải transcript."); }
  }

  return <main className="studio">
    <header className="header"><div className="brand"><span className="brand-icon">声</span>Audio Studio</div><span className="header-note">Chinese transcript workspace</span></header>
    <section className="hero">
      <div className="eyebrow">YOUTUBE → 中文逐字稿</div>
      <h1>Biến giọng nói tiếng Trung<br />thành bản chép sạch.</h1>
      <p>Dán liên kết YouTube. Studio sẽ lấy audio, phát hiện lời nói và tạo transcript tiếng Trung có thể tải về.</p>
      <form onSubmit={start} className="convert-form"><label htmlFor="youtube-url" className="sr-only">YouTube URL</label><input id="youtube-url" type="url" required placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(event) => setUrl(event.target.value)} /><button type="submit" disabled={busy}>{busy ? "Đang tạo…" : "Convert"} ↗</button></form>
      {message && <p className="alert" role="alert">{message}</p>}
      <div className="hero-foot"><span>01 · Audio only</span><span>02 · Speech detection</span><span>03 · Chinese transcript</span></div>
    </section>
    <section className="jobs-section">
      <div className="section-head"><div><span className="eyebrow">WORKSPACE</span><h2>Jobs <span className="count">{jobs.length}</span></h2></div><button className="refresh" onClick={() => void refresh()} type="button">↻ Làm mới</button></div>
      <div className="table-wrap"><table><thead><tr><th>Name</th><th>Duration</th><th>Status</th><th>Progress</th><th>Created</th><th>Output</th></tr></thead><tbody>
        {jobs.map((job) => <tr key={job.id}>
          <td className="name-cell"><strong title={job.name}>{job.name}</strong><small>{job.id.slice(0, 8)}</small></td>
          <td>{duration(job.duration_ms)}</td>
          <td><span className={`status status-${job.status.toLowerCase()}`}><i />{labels[job.status]}</span>{job.error && <small className="error-detail" title={job.error}>{job.error}</small>}</td>
          <td><div className="progress-row"><span>{job.progress}%</span><div className="progress-track"><div style={{ width: `${job.progress}%` }} /></div></div>{job.status === "VAD" && job.processed_ms ? <small>{duration(job.processed_ms)} / {duration(job.duration_ms)}</small> : job.chunks_total ? <small>{job.chunks_done || 0}/{job.chunks_total} đoạn</small> : null}</td>
          <td>{new Date(job.created_at).toLocaleString("vi-VN")}</td>
          <td className="output-cell">{job.status === "COMPLETED" ? <><button type="button" onClick={() => void view(job.id)}>{selected === job.id ? "Đóng" : "Xem"}</button><a href={`/api/jobs/${job.id}/transcript?download=1`}>Tải MD ↓</a></> : job.status === "FAILED" ? <button type="button" onClick={() => void retry(job.id)}>Thử lại ↻</button> : <span>—</span>}</td>
        </tr>)}
      </tbody></table>{!jobs.length && <div className="empty"><span>◎</span><strong>Chưa có job nào</strong><p>Nhập URL YouTube ở trên để bắt đầu.</p></div>}</div>
      {selected && <div className="transcript-panel"><div className="transcript-head"><strong>Transcript · 中文</strong><a href={`/api/jobs/${selected}/transcript?download=1`}>Tải transcript.zh.md ↓</a></div><div className="transcript-body">{transcript}</div></div>}
    </section><footer>Audio Studio <span>·</span> Chinese speech to text</footer>
  </main>;
}
