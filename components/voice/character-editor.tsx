"use client";
import { useEffect, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import { characterRanks, characterRoles, type Character, type CharacterSheet } from "@/lib/shared/address-profiles";

// Character sheet (L1): drafted by the worker, corrected here, applied on Reprocess from Moderation.
export default function CharacterEditor({jobId}:{jobId:string}){
  const { tr } = useLanguage();
  const [sheet,setSheet]=useState<CharacterSheet|null>(null),[editable,setEditable]=useState(false),[loaded,setLoaded]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    fetch(`/api/jobs/${jobId}/characters`,{cache:"no-store",signal:controller.signal}).then(r=>r.json()).then(d=>{setSheet(d.sheet||null);setEditable(!!d.editable);setLoaded(true);setMessage("");}).catch(()=>{});
    return()=>controller.abort();
  },[jobId]);
  if(!loaded)return null;
  if(!sheet)return <p className="character-empty">{tr("characterSheetMissing")}</p>;
  // Any manual edit marks the row as confirmed (auto=false), which allows gender corrections.
  const update=(index:number,patch:Partial<Character>)=>setSheet({...sheet,characters:sheet.characters.map((c,i)=>i===index?{...c,...patch,auto:false}:c)});
  const add=()=>setSheet({...sheet,characters:[...sheet.characters,{id:"",source:"",aliases:[],target:"",gender:null,role:"other",rank:"peer",third:"",you:"",auto:false}]});
  const remove=(index:number)=>setSheet({...sheet,characters:sheet.characters.filter((_,i)=>i!==index)});
  async function save(){
    if(!sheet)return;
    setBusy(true);setMessage("");
    const body={...sheet,characters:sheet.characters.map(c=>({...c,id:c.id||c.source,aliases:c.aliases.length?c.aliases:[c.source]}))};
    try{const r=await fetch(`/api/jobs/${jobId}/characters`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw new Error(d.error);setSheet(d.sheet);setMessage(tr("characterSheetSaved"));}
    catch(e){setMessage(e instanceof Error?tr(e.message):tr("Không lưu được bảng nhân vật."));}
    finally{setBusy(false);}
  }
  return <section className="character-editor">
    <h3>{tr("Nhân vật & xưng hô")}</h3>
    <p className="section-description">{tr("characterSheetHelp")}</p>
    <div className="table-wrap"><table>
      <thead><tr><th>{tr("Tên gốc")}</th><th>{tr("Bí danh")}</th><th>{tr("Tên tiếng Việt")}</th><th>{tr("Giới tính")}</th><th>{tr("Vai trò")}</th><th>{tr("Vai vế")}</th><th>{tr("Ngôi thứ ba")}</th><th>{tr("Gọi trực tiếp")}</th><th><span className="sr-only">{tr("Xóa")}</span></th></tr></thead>
      <tbody>{sheet.characters.map((c,i)=><tr key={i} className={c.auto?"character-auto":undefined}>
        <td><input aria-label={tr("Tên gốc")} value={c.source} maxLength={20} disabled={!editable} onChange={e=>update(i,{source:e.target.value})}/></td>
        <td><input aria-label={tr("Bí danh")} value={c.aliases.join(", ")} maxLength={120} disabled={!editable} onChange={e=>update(i,{aliases:e.target.value.split(/[,，]/).map(a=>a.trim()).filter(Boolean).slice(0,10)})}/></td>
        <td><input aria-label={tr("Tên tiếng Việt")} value={c.target} maxLength={40} disabled={!editable} onChange={e=>update(i,{target:e.target.value})}/></td>
        <td><select aria-label={tr("Giới tính")} value={c.gender||""} disabled={!editable} onChange={e=>update(i,{gender:(e.target.value||null) as Character["gender"]})}><option value="">{tr("Chưa rõ")}</option><option value="female">{tr("Nữ")}</option><option value="male">{tr("Nam")}</option></select></td>
        <td><select aria-label={tr("Vai trò")} value={c.role} disabled={!editable} onChange={e=>update(i,{role:e.target.value as Character["role"]})}>{characterRoles.map(r=><option key={r} value={r}>{tr(`role.${r}`)}</option>)}</select></td>
        <td><select aria-label={tr("Vai vế")} value={c.rank} disabled={!editable} onChange={e=>update(i,{rank:e.target.value as Character["rank"]})}>{characterRanks.map(r=><option key={r} value={r}>{tr(`rank.${r}`)}</option>)}</select></td>
        <td><input aria-label={tr("Ngôi thứ ba")} value={c.third} placeholder={tr("theo profile")} maxLength={20} disabled={!editable} onChange={e=>update(i,{third:e.target.value})}/></td>
        <td><input aria-label={tr("Gọi trực tiếp")} value={c.you} placeholder={tr("theo profile")} maxLength={20} disabled={!editable} onChange={e=>update(i,{you:e.target.value})}/></td>
        <td><button type="button" className="text-button" disabled={!editable} onClick={()=>remove(i)} aria-label={tr("Xóa")}>✕</button></td>
      </tr>)}</tbody>
    </table></div>
    <div className="character-actions">
      <button type="button" className="text-button" disabled={!editable||sheet.characters.length>=200} onClick={add}>{tr("Thêm nhân vật")}</button>
      <button type="button" className="action-button" disabled={!editable||busy} onClick={()=>void save()}>{tr("Lưu bảng nhân vật")}</button>
    </div>
    {!editable&&<small>{tr("Pause or finish the current run first")}</small>}
    {message&&<p role="status">{message}</p>}
  </section>;
}
