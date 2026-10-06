"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import { useState } from "react";

// Basic holds a run before paid Voice generation (status AWAITING_REVIEW) until the user decides.
export default function ReviewActions({id,scope="workflows",onChanged,onNotice}:{id:string;scope?:"workflows"|"tools";onChanged:()=>void|Promise<void>;onNotice:(message:string)=>void}){
  const { tr } = useLanguage();
  const [busy,setBusy]=useState(false);
  async function decide(decision:"continue"|"finish"){
    if(decision==="finish"&&!window.confirm(tr("reviewFinishConfirm")))return;
    setBusy(true);
    try{
      const response=await fetch(`/api/${scope==="tools"?"tools":"jobs"}/${id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({decision})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||tr("Không gửi được yêu cầu."));
      onNotice(tr(decision==="continue"?"reviewContinued":"reviewFinished"));
      await onChanged();
    }catch(error){onNotice(error instanceof Error?tr(error.message):tr("Không gửi được yêu cầu."));}
    finally{setBusy(false);}
  }
  return <div className="review-actions" role="group" aria-label={tr("reviewPrompt")}>
    <small>{tr("reviewPrompt")}</small>
    <button type="button" disabled={busy} onClick={()=>void decide("continue")}>{tr("Tiếp tục tạo giọng")}</button>
    <button type="button" disabled={busy} onClick={()=>void decide("finish")}>{tr("Kết thúc")}</button>
  </div>;
}
