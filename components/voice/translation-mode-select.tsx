"use client";
import { useId } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import type { TranslationMode } from "@/lib/shared/translation-modes";

const options: {id: TranslationMode; label: string; description: string}[] = [
  {id: "normal", label: "Normal", description: "translationModeNormal"},
  {id: "genius", label: "Genius (Fast and accurate)", description: "translationModeGenius"},
];

// Normal keeps the local model; Genius sends Translation to Gemini through the gateway.
export default function TranslationModeSelect({value,onChange}:{value:TranslationMode;onChange:(value:TranslationMode)=>void}){
  const { tr } = useLanguage();
  const id=useId();
  const active=options.find(item=>item.id===value);
  return <div className="voice-select mode-select">
    <div className="voice-style-select">
      <span id={`${id}-label`}>{tr("Chế độ dịch")}</span>
      <div className="voice-style-options" role="radiogroup" aria-labelledby={`${id}-label`}>
        {options.map(item=><button key={item.id} type="button" role="radio" aria-checked={value===item.id} className={`voice-style-option${value===item.id?' selected':''}`} onClick={()=>onChange(item.id)}>{tr(item.label)}</button>)}
      </div>
      {active&&<small className="voice-style-description">{tr(active.description)}</small>}
    </div>
  </div>;
}
