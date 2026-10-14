"use client";
import { useId } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import { addressProfiles } from "@/lib/shared/address-profiles";

// Forms of address (L0). Suggested by the voice style, applied at Moderation.
export default function AddressProfileSelect({value,onChange}:{value:string;onChange:(value:string)=>void}){
  const { tr } = useLanguage();
  const id=useId();
  const active=addressProfiles.find(item=>item.id===(value||'neutral'));
  return <div className="voice-select address-select">
    <div className="voice-style-select">
      <span id={`${id}-label`}>{tr("Xưng hô")}</span>
      <div className="voice-style-options" role="radiogroup" aria-labelledby={`${id}-label`}>
        {addressProfiles.map(item=><button key={item.id} type="button" role="radio" aria-checked={(value||'neutral')===item.id} className={`voice-style-option${(value||'neutral')===item.id?' selected':''}`} onClick={()=>onChange(item.id)}>{tr(item.label)}</button>)}
      </div>
      {active&&<small className="voice-style-description">{tr(active.description)}</small>}
    </div>
  </div>;
}
