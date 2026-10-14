"use client";
import { useLanguage } from "@/lib/i18n/language-context";

// Basic only: unticked runs stop before paid Voice generation (status AWAITING_REVIEW).
export default function AutoTtsToggle({checked,onChange}:{checked:boolean;onChange:(value:boolean)=>void}){
  const { tr } = useLanguage();
  return <label className="auto-tts-toggle">
    <input type="checkbox" checked={checked} onChange={event=>onChange(event.target.checked)}/>
    <span>{tr("autoTts")}</span>
    {!checked&&<small>{tr("autoTtsHelp")}</small>}
  </label>;
}
