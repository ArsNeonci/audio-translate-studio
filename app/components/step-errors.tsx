"use client";
import { useLanguage } from "@/lib/language-context";
import {useLicense} from "@/app/components/license-status";
import { useState } from "react";
import type { Job, Step } from "@/lib/jobs";
import {useNotice} from './use-notice';
import { localizeGuide } from '@/lib/localized-guides';

const steps: Step[] = ["DOWNLOAD", "TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"];
type Guide = {cause: string; config: string; checks_and_fixes: string[]; commands: string[]};

export default function StepErrors({job}: {job: Pick<Job,"id"|"steps"|"artifacts"|"retry_step"|"tool_steps"> & {status:string}}) {
  const { tr, language } = useLanguage();
  const license = useLicense();
  const [open, setOpen] = useState<Step | null>(null);
  const [guide, setGuide] = useState<Guide | null>(null);
  const [busy, setBusy] = useState<{step: Step; failedAt?: string} | null>(null);
  const [message, setMessage] = useNotice();
  async function show(step: Step, fix: boolean) {
    setOpen(step); setGuide(null); setMessage("");
    if (!fix) return;
    try {
      const response = await fetch(`/api/jobs/${job.id}/steps/${step}`, {cache: "no-store"});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      setGuide(result.fix_guide);
    } catch(e) {setMessage(e instanceof Error ? e.message : tr("Không tải được hướng dẫn."));}
  }
  async function retry(step: Step) {
    if(!window.confirm(tr("retryConfirm", {stage: tr(step)})))return;
    setBusy({step, failedAt: job.steps?.[step]?.error?.failed_at}); setMessage("");
    try {
      const response = await fetch(`/api/jobs/${job.id}/steps/${step}`, {method: "POST"});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : tr("Không thể retry."));
      setOpen(null); setGuide(null); setMessage(tr("Đã xóa dữ liệu giai đoạn lỗi và xếp hàng chạy lại riêng giai đoạn này."));
    } catch(e) {setMessage(e instanceof Error ? e.message : tr("Không thể retry.")); setBusy(null);}
  }
  return <div className="step-errors">
    {(job.tool_steps||steps).map(step => {
      const item = job.steps?.[step];
      const localizedGuide = guide && item?.error ? localizeGuide(guide, item.error.error_code, language) : null;
      const legacyCompleted = step === "DOWNLOAD" || step === "TRANSCRIPTION" ? job.artifacts?.zh : step === "TRANSLATION" ? job.artifacts?.vi : step === "MODERATION" ? job.artifacts?.moderated : job.artifacts?.voice;
      const state = item?.state || (legacyCompleted ? "COMPLETED" : "PENDING");
      const retrying = job.retry_step === step || (busy?.step === step && busy.failedAt === item?.error?.failed_at && job.status === "FAILED");
      return <div className="step-state" key={step}><strong>{tr(step)}</strong><span>{state === "COMPLETED" ? tr("✅ Completed") : state === "RUNNING" ? (item?.retry_count ? tr("Retrying / Running") : tr("Running")) : retrying ? tr("Retrying / Waiting") : state === "FAILED" ? tr("❌ Failed") : ['CANCELLED','PAUSED'].includes(state) ? tr("⏸ Đã dừng") : tr("○ Waiting")}</span>
        {state === "FAILED" && <div className="step-actions"><button className="text-button" onClick={() => void show(step, false)}>{tr("View Error")}</button>
          {item?.error?.recoverable_manually && <button className="text-button" onClick={() => void show(step, true)}>{tr("View Fix Guide")}</button>}
          <button className="action-button" disabled={!license.allowed || retrying || job.status !== "FAILED"} onClick={() => void retry(step)}>{tr("Chạy lại giai đoạn")}</button><small>{tr("Chỉ xóa dữ liệu của giai đoạn lỗi, giữ kết quả trước đó.")}</small></div>}
        {open === step && item?.error && <div className="fix-guide"><p className="alert">{item.error.error_code}: {tr(item.error.error_message)}</p><small>{item.error.failed_at} · {item.error.error_type} · {tr("Retry count:")} {item.retry_count}</small>
          {localizedGuide && <><p>{localizedGuide.cause}</p><p>{tr("File/config:")} {localizedGuide.config}</p><ol>{localizedGuide.checks_and_fixes.map((text,i) => <li key={i}>{text}</li>)}</ol>{localizedGuide.commands.map((command,i) => <pre key={i}>{command}</pre>)}<p>{tr("Sau khi sửa, bấm Retry Step.")}</p></>}
        </div>}
      </div>;
    })}
    {message && <p role="status">{message}</p>}
  </div>;
}
