"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import {useEffect,useId,useRef,useState} from "react";
import {useNotice} from '@/components/common/use-notice';
import { translateVoiceDescription } from '@/lib/i18n/ui-text';
import { voiceStyles } from '@/lib/shared/voice-styles';
type Voice={id:string;label:string;description:string;preview_url?:string|null};
type StyleOption={id:string;recommended_voice_id:string|null};
// Without onStyleChange the picker renders voices only (legacy callers).
export default function VoiceSelect({value,onChange,style,onStyleChange}:{value:string;onChange:(value:string)=>void;style?:string;onStyleChange?:(value:string)=>void}){
  const { tr, language } = useLanguage();
  const [loadFailed,setLoadFailed]=useState(false),[voices,setVoices]=useState<Voice[]>([]),[open,setOpen]=useState(false),[playing,setPlaying]=useState(''),[previewStatus,setPreviewStatus]=useState(''),[preferred,setPreferred]=useState(''),[styleOptions,setStyleOptions]=useState<StyleOption[]>([]),[preferredStyle,setPreferredStyle]=useState('');const [error,setError]=useNotice();
  const id=useId(),root=useRef<HTMLDivElement>(null),toggle=useRef<HTMLButtonElement>(null),audio=useRef<HTMLAudioElement>(null),request=useRef(0);
  useEffect(()=>{
    const controller=new AbortController();let stopped=false;let timer:ReturnType<typeof setTimeout>;
    async function load(){try{const response=await fetch('/api/voices',{cache:'no-store',signal:controller.signal});const data=await response.json();if(!response.ok)throw new Error(data.error);if(stopped)return;setVoices(data.voices);setPreferred(data.selected_voice_id);setStyleOptions(data.styles||[]);setPreferredStyle(data.selected_style||'');setPreviewStatus(data.preview_status);setLoadFailed(false);setError('');if(['WAITING_IDLE','BUILDING'].includes(data.preview_status))timer=setTimeout(()=>void load(),15000);}catch(e){if(stopped)return;const code=e instanceof Error?e.message:String(e);setLoadFailed(true);setError(/^[A-Z_]{3,40}$/.test(code)?`voiceListError.${code}`:'voiceListError.OTHER');timer=setTimeout(()=>void load(),10000);}}  // retry quietly: the cause (no licence lease yet, offline) often clears by itself
    void load();return()=>{stopped=true;controller.abort();clearTimeout(timer);};
  },[setError]);
  useEffect(()=>{if(!value&&preferred)onChange(preferred);},[value,preferred,onChange]);
  useEffect(()=>{if(onStyleChange&&!style&&preferredStyle)onStyleChange(preferredStyle);},[style,preferredStyle,onStyleChange]);
  function chooseStyle(id:string){
    if(!onStyleChange)return;onStyleChange(id);
    // Recommendation only: the voice list below still accepts any preset.
    const recommended=styleOptions.find(option=>option.id===id)?.recommended_voice_id;
    if(recommended&&voices.some(voice=>voice.id===recommended))onChange(recommended);
  }
  const activeStyle=voiceStyles.find(item=>item.id===(style||'default'));
  useEffect(()=>{if(!open)return;const close=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false);};document.addEventListener('pointerdown',close);root.current?.querySelector<HTMLButtonElement>(`[data-selected="true"]`)?.focus();return()=>document.removeEventListener('pointerdown',close);},[open]);
  useEffect(()=>()=>{request.current++;audio.current?.pause();},[]);
  async function preview(voice:Voice){
    if(!audio.current||!voice.preview_url)return;
    const token=++request.current;audio.current.pause();
    if(playing===voice.id){setPlaying('');return;}
    audio.current.src=voice.preview_url;setPlaying(voice.id);setError('');
    try{await audio.current.play();}catch{if(token===request.current){setPlaying('');setError(tr("Không phát được mẫu giọng. Vui lòng thử lại."));}}
  }
  const selected=voices.find(voice=>voice.id===value);
  const waiting=previewStatus==='WAITING_IDLE'?tr("Mẫu giọng sẽ được tạo sau khi workflow đang chạy hoàn tất."):previewStatus==='BUILDING'?tr("Đang tạo mẫu giọng một lần…"):previewStatus==='FAILED'?tr("Tạo mẫu giọng chưa thành công."):tr("Mẫu giọng chưa được tạo.");
  return <div className="voice-select" ref={root} onKeyDown={event=>{if(event.key==='Escape'){setOpen(false);toggle.current?.focus();}}}>
    {onStyleChange&&<div className="voice-style-select">
      <span id={`${id}-style-label`}>{tr("Kiểu giọng")}</span>
      <div className="voice-style-options" role="radiogroup" aria-labelledby={`${id}-style-label`}>
        {voiceStyles.map(item=><button key={item.id} type="button" role="radio" aria-checked={(style||'default')===item.id} className={`voice-style-option${(style||'default')===item.id?' selected':''}`} disabled={!voices.length} onClick={()=>chooseStyle(item.id)}>{tr(item.label)}</button>)}
      </div>
      {activeStyle&&<small className="voice-style-description">{tr(activeStyle.description)}{activeStyle.id!=='default'&&<> {tr("voiceStyleCues")}</>}</small>}
    </div>}
    <span id={`${id}-label`}>{tr("Vietnamese Voice")}</span>
    <div className="voice-picker-shell"><button ref={toggle} type="button" className="voice-picker-toggle" aria-labelledby={`${id}-label ${id}-value`} aria-expanded={open} aria-haspopup="dialog" aria-controls={`${id}-choices`} disabled={!voices.length} onClick={()=>setOpen(!open)}><span id={`${id}-value`}>{selected?`${selected.label}${selected.description?` · ${translateVoiceDescription(selected.description, language)}`:''}`:voices.length?tr("Chọn giọng"):loadFailed?tr("voiceListFailed"):tr("Đang tải giọng…")}</span><span aria-hidden="true">⌄</span></button>
    {open&&<div id={`${id}-choices`} role="dialog" aria-labelledby={`${id}-label`} className="voice-options">
      {voices.map(voice=><div key={voice.id} className={`voice-option${value===voice.id?' selected':''}`}>
        <button type="button" className="voice-option-name" data-selected={value===voice.id} aria-pressed={value===voice.id} onClick={()=>{onChange(voice.id);setOpen(false);toggle.current?.focus();}}>{voice.label}<span className="voice-description">{translateVoiceDescription(voice.description, language)}</span></button>
        <button type="button" className="voice-preview-play" aria-label={tr(playing === voice.id ? "voiceStop" : "voicePreview", {name: voice.label})} title={voice.preview_url?tr("voiceSample", {name: voice.label}):waiting} disabled={!voice.preview_url} onClick={()=>void preview(voice)}><span aria-hidden="true">{playing===voice.id?'■':'▶'}</span></button>
      </div>)}
    </div>}</div>
    <audio ref={audio} preload="none" onEnded={()=>{setPlaying('');}} onError={()=>{setPlaying('');setError(tr("Không đọc được file mẫu giọng."));}}/>
    {playing&&<span role="status">{tr("Đang nghe:")} {voices.find(voice => voice.id === playing)?.label || playing}</span>}
    {voices.some(voice=>!voice.preview_url)&&<small>{waiting} {tr("Bấm nghe thử chỉ phát file lưu sẵn, không chạy model.")}</small>}
    {error&&<span role="alert">{tr(error)}</span>}
  </div>;
}
