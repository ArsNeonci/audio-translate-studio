"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import {useLicense} from "@/components/license/license-status";
import { useRef, useState } from "react";
import type { Job, Step } from "@/lib/server/jobs";
import {useNotice} from '@/components/common/use-notice';
import { localizeGuide } from '@/lib/i18n/localized-guides';
import {elapsed} from '@/lib/shared/format';

const steps: Step[] = ["DOWNLOAD", "TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"];
type Guide = {cause: string; config: string; checks_and_fixes: string[]; commands: string[]};

export default function StepErrors({job}: {job: Pick<Job,"id"|"steps"|"artifacts"|"retry_step"|"tool_steps"|"translation_failures"> & {status:string}}) {
  const { tr, language } = useLanguage();
  const license = useLicense();
  const [open, setOpen] = useState<Step | null>(null);
  const [guide, setGuide] = useState<Guide | null>(null);
  const [busy, setBusy] = useState<{step: Step; failedAt?: string} | null>(null);
  const [message, setMessage] = useNotice();
  const pending = useRef(false);
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
  async function retry(step: Step, continuing=false) {
    if(pending.current)return;
    if(!continuing&&!window.confirm(tr("retryConfirm", {stage: tr(step)})))return;
    pending.current=true;
    setBusy({step, failedAt: job.steps?.[step]?.error?.failed_at}); setMessage("");
    try {
      const response = await fetch(continuing?`/api/jobs/${job.id}/resume`:`/api/jobs/${job.id}/steps/${step}`, {method: "POST"});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : tr("Không thể retry."));
      setOpen(null); setGuide(null); setMessage(continuing?tr('translationContinueNotice'):tr("Đã xóa dữ liệu giai đoạn lỗi và xếp hàng chạy lại riêng giai đoạn này."));
    } catch(e) {setMessage(e instanceof Error ? e.message : tr("Không thể retry.")); setBusy(null);}
    finally {pending.current=false;}
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
          {step==='TRANSLATION'&&<><button className="action-button" disabled={!license.allowed||retrying||job.status!=='FAILED'} onClick={()=>void retry(step,true)}>{tr('Tiếp tục giai đoạn')}</button><small>{tr('translationContinueHelp')}</small></>}
          <button className="action-button" disabled={!license.allowed || retrying || job.status !== "FAILED"} onClick={() => void retry(step)}>{tr("Chạy lại giai đoạn")}</button><small>{tr("Chỉ xóa dữ liệu của giai đoạn lỗi, giữ kết quả trước đó.")}</small></div>}
        {open === step && item?.error && <div className="fix-guide"><p className="alert">{item.error.error_code}: {tr(item.error.error_message)}</p><small>{item.error.failed_at} · {item.error.error_type} · {tr("Retry count:")} {item.retry_count}</small>
          {step==='TRANSLATION'&&job.translation_failures?.map(failure=><div key={`${failure.row}-${failure.part}`}><p>{tr('translationSegmentFailure',{row:failure.row,part:failure.part+1,start:elapsed(failure.start_ms),end:elapsed(failure.end_ms),count:failure.failure_count})}</p>{failure.source&&<pre>{failure.source}</pre>}<p>{failure.reason}</p>{failure.attempts.map((attempt,index)=><details key={index}><summary>{tr('translationRejectedDraft',{attempt:index+1,seed:attempt.seed})}</summary><pre>{attempt.draft}</pre><small>{attempt.reason}</small></details>)}</div>)}
          {localizedGuide && <><p>{localizedGuide.cause}</p><p>{tr("File/config:")} {localizedGuide.config}</p><ol>{localizedGuide.checks_and_fixes.map((text,i) => <li key={i}>{text}</li>)}</ol>{localizedGuide.commands.map((command,i) => <pre key={i}>{command}</pre>)}<p>{tr("Sau khi sửa, bấm Retry Step.")}</p></>}
        </div>}
      </div>;
    })}
    {message && <p role="status">{message}</p>}
  </div>;
}
