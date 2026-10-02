"use client";
import {useRef,useState} from 'react';
import type {Job} from '@/lib/jobs';
import {runNumber} from '@/lib/format';

export default function WorkflowActions({job,onChanged,onNotice,canResume=true}:{job:Job;onChanged:()=>Promise<void>;onNotice:(message:string)=>void;canResume?:boolean}){
  const [busy,setBusy]=useState(false);
  const pending=useRef(false);
  const stopped=['PAUSED','CANCELLED'].includes(job.status);
  const active=!['COMPLETED','FAILED','CANCELLED','PAUSED','PARTIAL','DELETING'].includes(job.status);
  const locked=busy||!!job.delete_requested||job.status==='DELETING';
  async function action(kind:'pause'|'resume'|'abort'){
    if(pending.current)return;
    if(kind==='abort'&&!window.confirm(`Hủy workflow #${runNumber(job.workflow_no)} và xóa toàn bộ audio, checkpoint, kết quả liên quan?\nKhông thể hoàn tác. Model, giọng mẫu và các workflow khác được giữ nguyên.`))return;
    pending.current=true;setBusy(true);
    try{
      const response=await fetch(`/api/jobs/${job.id}/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},...(kind==='abort'?{body:JSON.stringify({confirm:job.workflow_no,scope:job.storage_scope||'workflows'})}:{})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||'Không gửi được yêu cầu.');
      onNotice(kind==='pause'?'Đã yêu cầu dừng sau task hiện tại và lưu checkpoint.':kind==='resume'?'Đã xếp hàng tiếp tục từ checkpoint.':data.deleted?'Đã hủy và xóa dữ liệu workflow.':'Đã yêu cầu hủy; dữ liệu sẽ được xóa sau khi worker dừng.');
      await onChanged();
    }catch(error){onNotice(error instanceof Error?error.message:'Không gửi được yêu cầu.');}
    finally{pending.current=false;setBusy(false);}
  }
  return <div className="workflow-actions" role="group" aria-label={`Thao tác workflow #${runNumber(job.workflow_no)}`} aria-busy={busy}>
    {active&&<button type="button" className="workflow-icon workflow-pause" title="Dừng giai đoạn" aria-label="Dừng giai đoạn" disabled={locked||!!job.pause_requested} onClick={()=>void action('pause')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg></button>}
    {stopped&&<button type="button" className="workflow-icon workflow-resume" title="Tiếp tục giai đoạn" aria-label="Tiếp tục giai đoạn" disabled={locked||!canResume} onClick={()=>void action('resume')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7Z"/></svg></button>}
    {job.status!=='COMPLETED'&&<button type="button" className="workflow-icon workflow-abort" title="Hủy và xóa workflow" aria-label="Hủy và xóa workflow" disabled={locked} onClick={()=>void action('abort')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>}
  </div>;
}
