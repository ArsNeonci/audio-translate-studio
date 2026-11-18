"use client";
import { useLanguage } from "@/lib/i18n/language-context";
import OverlayBoard, { fit } from "@/components/overlay/overlay-board";
import { FRAME, type OverlayAsset, type OverlayItem, type OverlayTemplate, type Orientation } from "@/components/overlay/overlay-types";

/** What is being edited: a saved template (with its id) or a new one. */
export type Draft = { id?: string; name: string; orientation: Orientation; items: OverlayItem[] };
export const draftOf = (template?: OverlayTemplate): Draft => template ? { id: template.id, name: template.name, orientation: template.orientation, items: template.items } : { name: "", orientation: "landscape", items: [] };

/** The frame, the numbers of the chosen picture, and the name and frame shape of the template. */
export default function OverlayEditor({ draft, assets, selected, dirty, busy, onSelect, onChange, onSave, onClose }:
  { draft: Draft; assets: OverlayAsset[]; selected: number | null; dirty: boolean; busy: boolean; onSelect: (index: number | null) => void; onChange: (next: Draft) => void; onSave: () => void; onClose: () => void }) {
  const { tr } = useLanguage();
  const { width, height } = FRAME[draft.orientation];
  const item = selected !== null ? draft.items[selected] : undefined;
  const asset = item ? assets.find(candidate => candidate.id === item.asset) : undefined;
  const items = (next: OverlayItem[]) => onChange({ ...draft, items: next });
  const edit = (patch: Partial<OverlayItem>) => { if (item && selected !== null) items(draft.items.map((current, i) => i === selected ? fit({ ...item, ...patch }, asset, draft.orientation) : current)); };
  const remove = (index: number) => { items(draft.items.filter((_, i) => i !== index)); onSelect(null); };
  const reorder = (by: number) => {
    if (selected === null) return;
    const target = selected + by;
    if (target < 0 || target >= draft.items.length) return;
    const next = [...draft.items]; [next[selected], next[target]] = [next[target], next[selected]];
    items(next); onSelect(target);
  };
  const number = (value: string) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const valid = draft.name.trim().length > 0 && draft.name.trim().length <= 60;

  return <section className="overlay-editor" aria-label={tr("overlaysBoard")}>
    <div className="overlay-meta">
      <label>{tr("overlaysName")}<input type="text" value={draft.name} maxLength={60} disabled={busy} onChange={event => onChange({ ...draft, name: event.target.value })} /></label>
      <label>{tr("overlaysOrientation")}<select value={draft.orientation} disabled={busy} onChange={event => { const orientation = event.target.value as Orientation; onChange({ ...draft, orientation, items: draft.items.map(each => fit(each, assets.find(candidate => candidate.id === each.asset), orientation)) }); }}>
        <option value="landscape">{tr("overlaysLandscape")}</option><option value="portrait">{tr("overlaysPortrait")}</option></select></label>
    </div>
    <div className="overlay-work">
      <OverlayBoard orientation={draft.orientation} items={draft.items} assets={assets} selected={selected} onSelect={onSelect} onChange={items} onRemove={remove} />
      <div className="overlay-props">
        {item ? <>
          <strong>{tr("overlaysItem", { name: asset?.name || "" })}</strong>
          <label>{tr("overlaysX")}<input type="number" min={0} max={width} step={1} value={Math.round(item.x * width)} disabled={busy} onChange={event => edit({ x: number(event.target.value) / width })} /></label>
          <label>{tr("overlaysY")}<input type="number" min={0} max={height} step={1} value={Math.round(item.y * height)} disabled={busy} onChange={event => edit({ y: number(event.target.value) / height })} /></label>
          <label>{tr("overlaysWidth")}<input type="number" min={Math.ceil(width * 0.02)} max={width} step={1} value={Math.round(item.w * width)} disabled={busy} onChange={event => edit({ w: number(event.target.value) / width })} /></label>
          <label>{tr("overlaysOpacity")} · {Math.round(item.opacity * 100)}%<input type="range" min={10} max={100} step={5} value={Math.round(item.opacity * 100)} disabled={busy} onChange={event => edit({ opacity: number(event.target.value) / 100 })} /></label>
          <div className="overlay-props-actions">
            <button type="button" className="text-button" disabled={busy || selected === draft.items.length - 1} onClick={() => reorder(1)}>{tr("overlaysFront")}</button>
            <button type="button" className="text-button" disabled={busy || selected === 0} onClick={() => reorder(-1)}>{tr("overlaysBack")}</button>
            <button type="button" className="text-button" disabled={busy} onClick={() => remove(selected as number)}>{tr("overlaysTakeOff")}</button>
          </div>
        </> : <small>{tr("overlaysFrameNote")}</small>}
      </div>
    </div>
    <div className="overlay-actions">
      <button type="button" className="action-button" disabled={busy || !valid || !dirty} onClick={onSave}>{tr(busy ? "overlaysSaving" : "overlaysSave")}</button>
      <button type="button" className="text-button" disabled={busy} onClick={onClose}>{tr("overlaysCancelEdit")}</button>
      {dirty && <small role="status">{tr("overlaysUnsaved")}</small>}
    </div>
  </section>;
}
