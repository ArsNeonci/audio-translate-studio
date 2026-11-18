"use client";
import { apiFetch, apiUrl, useNotice } from "@audio/ui";
import { useRef, useState } from "react";
import SiteHeader from "@/components/layout/site-header";
import OverlayEditor, { draftOf, type Draft } from "@/components/overlay/overlay-editor";
import { fit } from "@/components/overlay/overlay-board";
import { useOverlays, type OverlayTemplate } from "@/components/overlay/overlay-types";
import { useLanguage } from "@/lib/i18n/language-context";

const IMAGE_TYPES = ".png,.jpg,.jpeg,.webp,.bmp,.ico,.gif,.svg";
const MAX_BYTES = 10 * 1024 ** 2;

/** A vector picture drawn to a PNG here (the server reads only raster pictures): at most 2048 px on its long side. */
async function rasterise(file: File): Promise<File> {
  const url = URL.createObjectURL(file);
  try {
    const picture = new Image();
    picture.src = url;
    await picture.decode();
    const width = picture.naturalWidth || 512, height = picture.naturalHeight || 512, scale = 2048 / Math.max(width, height);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale)); canvas.height = Math.max(1, Math.round(height * scale));
    canvas.getContext("2d")?.drawImage(picture, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("OVERLAY_UNREADABLE");
    return new File([blob], file.name.replace(/\.svg$/i, ".png"), { type: "image/png" });
  } finally { URL.revokeObjectURL(url); }
}

const same = (a: Draft | null, b: Draft | null) => JSON.stringify(a) === JSON.stringify(b);

export default function Overlays() {
  const { tr } = useLanguage();
  const { data, reload } = useOverlays();
  const [message, setMessage] = useNotice();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState<Draft | null>(null);       // the draft as last saved: what "unsaved changes" is measured against
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const dirty = !!draft && !same(draft, saved);
  const assets = data?.assets || [], templates = data?.templates || [];

  const fail = (error: unknown) => setMessage(tr(error instanceof Error ? error.message : "X901"));
  async function call(path: string, init: RequestInit) {
    const response = await apiFetch(path, init);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || "X901");
    return body;
  }
  const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const leave = () => !dirty || window.confirm(tr("overlaysDiscard"));

  function open(next: Draft | null, baseline: Draft | null = next) {
    if (!leave()) return;
    setDraft(next); setSaved(baseline); setSelected(null);
  }

  async function add(files: FileList | null) {
    const file = files?.[0];
    if (picker.current) picker.current.value = "";
    if (!file) return;
    setBusy(true); setMessage("");
    try {
      if (file.size > MAX_BYTES) throw new Error("OVERLAY_TOO_BIG");
      const upload = /\.svg$/i.test(file.name) || file.type === "image/svg+xml" ? await rasterise(file) : file;
      await call(`/api/overlays/assets?${new URLSearchParams({ name: upload.name })}`, { method: "POST", headers: { "Content-Type": upload.type || "application/octet-stream" }, body: upload });
      await reload();
    } catch (error) { fail(error instanceof DOMException ? new Error("OVERLAY_UNREADABLE") : error); }
    finally { setBusy(false); }
  }

  async function removeAsset(id: string, name: string) {
    if (!window.confirm(tr("overlaysRemoveConfirm", { name }))) return;
    setMessage("");
    try { await call(`/api/overlays/assets/${id}`, { method: "DELETE" }); await reload(); } catch (error) { fail(error); }
  }

  function putOnBoard(id: string) {
    if (!draft) return;
    const picture = assets.find(asset => asset.id === id);
    const first = fit({ asset: id, x: 0.04, y: 0.04, w: 0.2, opacity: 1 }, picture, draft.orientation);
    setDraft({ ...draft, items: [...draft.items, first] }); setSelected(draft.items.length);
  }

  async function save() {
    if (!draft) return;
    setBusy(true); setMessage("");
    try {
      const { template } = await call("/api/overlays/templates", json("POST", { ...draft, name: draft.name.trim() }));
      const next = draftOf(template as OverlayTemplate);
      setDraft(next); setSaved(next); await reload(); setMessage(tr("overlaysSaved"));
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  }

  async function removeTemplate(template: OverlayTemplate) {
    if (!window.confirm(tr("overlaysDeleteConfirm", { name: template.name }))) return;
    setMessage("");
    try {
      await call(`/api/overlays/templates/${template.id}`, { method: "DELETE" });
      if (draft?.id === template.id) { setDraft(null); setSaved(null); }
      await reload();
    } catch (error) { fail(error); }
  }

  async function makeDefault(template: OverlayTemplate, on: boolean) {
    setMessage("");
    try { await call("/api/overlays/defaults", json("PUT", { orientation: template.orientation, template: on ? template.id : null })); await reload(); } catch (error) { fail(error); }
  }

  return <main className="studio"><SiteHeader />
    <section className="hero overlay-page">
      <h1>{tr("overlaysTitle")}</h1>
      <p>{tr("overlaysIntro")}</p>

      <div className="overlay-block">
        <div className="overlay-head">
          <h2>{tr("overlaysLibrary")}</h2>
          <button type="button" className="action-button" disabled={busy} onClick={() => picker.current?.click()}>{tr(busy ? "overlaysAdding" : "overlaysAdd")}</button>
          <input ref={picker} type="file" accept={IMAGE_TYPES} hidden aria-label={tr("overlaysAdd")} onChange={event => void add(event.target.files)} />
        </div>
        <small>{tr("overlaysAddHelp")}</small>
        {assets.length ? <ul className="overlay-library">{assets.map(asset => <li key={asset.id} className="overlay-asset">
          <span className="overlay-thumb">
            {/* eslint-disable-next-line @next/next/no-img-element -- a local API picture */}
            <img src={apiUrl(`/api/overlays/assets/${asset.id}`)} alt={asset.name} loading="lazy" />
          </span>
          <strong title={asset.name}>{asset.name}</strong>
          <small>{asset.width}×{asset.height}</small>
          <span className="overlay-asset-actions">
            <button type="button" className="text-button" disabled={!draft || busy} onClick={() => putOnBoard(asset.id)}>{tr("overlaysPutOnBoard")}</button>
            <button type="button" className="text-button" disabled={busy} onClick={() => void removeAsset(asset.id, asset.name)}>{tr("overlaysRemove")}</button>
          </span>
        </li>)}</ul> : <p className="overlay-empty">{tr("overlaysEmpty")}</p>}
      </div>

      <div className="overlay-block">
        <div className="overlay-head">
          <h2>{tr("overlaysTemplates")}</h2>
          <button type="button" className="action-button" disabled={busy} onClick={() => open(draftOf())}>{tr("overlaysNew")}</button>
        </div>
        {templates.length ? <ul className="overlay-templates">{templates.map(template => {
          const isDefault = data?.defaults[template.orientation] === template.id;
          return <li key={template.id} className={draft?.id === template.id ? "editing" : undefined}>
            <strong>{template.name}</strong>
            <small>{tr(template.orientation === "landscape" ? "overlaysLandscape" : "overlaysPortrait")} · {tr("overlaysItems", { count: template.items.length })}</small>
            {isDefault && <span className="overlay-badge">{tr("overlaysIsDefault")}</span>}
            <span className="overlay-template-actions">
              <button type="button" className="text-button" disabled={busy} onClick={() => open(draftOf(template))}>{tr("overlaysEdit")}</button>
              <button type="button" className="text-button" disabled={busy} onClick={() => open({ ...draftOf(template), id: undefined, name: `${template.name} (2)` }, null)}>{tr("overlaysDuplicate")}</button>
              <button type="button" className="text-button" disabled={busy} onClick={() => void makeDefault(template, !isDefault)}>{tr(isDefault ? "overlaysClearDefault" : "overlaysDefault")}</button>
              <button type="button" className="text-button" disabled={busy} onClick={() => void removeTemplate(template)}>{tr("overlaysDelete")}</button>
            </span>
          </li>;
        })}</ul> : <p className="overlay-empty">{tr("overlaysNoTemplates")}</p>}
      </div>

      {draft && <OverlayEditor draft={draft} assets={assets} selected={selected} dirty={dirty} busy={busy} onSelect={setSelected} onChange={setDraft} onSave={() => void save()} onClose={() => open(null)} />}
      {message && <p className="alert" role="status">{message}</p>}
    </section>
  </main>;
}
