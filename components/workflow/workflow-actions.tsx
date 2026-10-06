"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import {useRef,useState} from 'react';
import type {Job} from '@/lib/server/jobs';
import {runNumber} from '@/lib/shared/format';
import ReviewActions from '@/components/workflow/review-actions';

export default function WorkflowActions({job,onChanged,onNotice,canResume=true}:{job:Job;onChanged:()=>Promise<void>;onNotice:(message:string)=>void;canResume?:boolean}){
  const { tr } = useLanguage();
  const [busy,setBusy]=useState(false);
  const pending=useRef(false);
  const stopped=['PAUSED','CANCELLED'].includes(job.status)||(job.status==='FAILED'&&job.steps?.TRANSLATION?.state==='FAILED');
  const active=!['COMPLETED','FAILED','CANCELLED','PAUSED','PARTIAL','DELETING','AWAITING_REVIEW'].includes(job.status);
  const locked=busy||!!job.delete_requested||job.status==='DELETING';
  async function action(kind:'pause'|'resume'|'abort'){
    if(pending.current)return;
    if(kind==='abort'&&!window.confirm(tr("abortConfirm", {number: runNumber(job.workflow_no)})))return;
    pending.current=true;setBusy(true);
    try{
      const response=await fetch(`/api/jobs/${job.id}/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},...(kind==='abort'?{body:JSON.stringify({confirm:job.workflow_no,scope:job.storage_scope||'workflows'})}:{})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||tr("Không gửi được yêu cầu."));
      onNotice(kind==='pause'?tr("Đã yêu cầu dừng sau task hiện tại và lưu checkpoint."):kind==='resume'?tr("Đã xếp hàng tiếp tục từ checkpoint."):data.deleted?tr("Đã hủy và xóa dữ liệu workflow."):tr("Đã yêu cầu hủy; dữ liệu sẽ được xóa sau khi worker dừng."));
      await onChanged();
    }catch(error){onNotice(error instanceof Error?error.message:tr("Không gửi được yêu cầu."));}
    finally{pending.current=false;setBusy(false);}
  }
  return <div className="workflow-actions" role="group" aria-label={`${tr("Thao tác workflow #")}${runNumber(job.workflow_no)}`} aria-busy={busy}>
    {job.status==='AWAITING_REVIEW'&&<ReviewActions id={job.id} onChanged={onChanged} onNotice={onNotice}/>}
    {active&&<button type="button" className="workflow-icon workflow-pause" title={tr("Dừng giai đoạn")} aria-label={tr("Dừng giai đoạn")} disabled={locked||!!job.pause_requested} onClick={()=>void action('pause')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg></button>}
    {stopped&&<button type="button" className="workflow-icon workflow-resume" title={tr("Tiếp tục giai đoạn")} aria-label={tr("Tiếp tục giai đoạn")} disabled={locked||!canResume} onClick={()=>void action('resume')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7Z"/></svg></button>}
    {job.status!=='COMPLETED'&&<button type="button" className="workflow-icon workflow-abort" title={tr("Hủy và xóa workflow")} aria-label={tr("Hủy và xóa workflow")} disabled={locked} onClick={()=>void action('abort')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>}
  </div>;
}
