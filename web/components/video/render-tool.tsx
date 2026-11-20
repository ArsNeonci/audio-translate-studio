"use client";
import { apiFetch, FilePicker } from "@audio/ui";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import FormSection from "@/components/common/form-section";
import { useOverlays } from "@/components/overlay/overlay-types";
import { gigabytes, type VideoClip } from "@/components/video/video-picker";

type Estimate = { files: VideoClip[]; error?: string; resolutions?: string[]; resolution?: string; overlay_used?: boolean; free_bytes?: number; needed_bytes?: number; enough?: boolean;
  plan?: { seconds: number; size_bytes: number | null; mode: string } };
const minutes = (seconds: number) => seconds < 90 ? `${Math.max(1, Math.round(seconds))} s` : `${Math.round(seconds / 60)} min`;
const clipLength = (ms: number) => { const s = Math.round(ms / 1000), h = Math.floor(s / 3600); return `${h ? h + ":" + String(Math.floor(s / 60) % 60).padStart(2, "0") : Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

/** Tools 8 and 9: one video of the person's, with their subtitle file drawn on it (8) or a logo template laid on it (9). The picture is encoded once and the
 *  sound is kept; the video stays where it is and is only read. */
export default function RenderTool({ mode, allowed, onQueued, onMessage }: { mode: "subtitle_burn" | "overlay"; allowed: boolean; onQueued: () => void; onMessage: (text: string) => void }) {
  const { t, tr } = useLanguage();
  const withSubtitle = mode === "subtitle_burn";
  const { data: library } = useOverlays();
  const [clip, setClip] = useState<VideoClip | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [resolution, setResolution] = useState("keep"), [quality, setQuality] = useState("high"), [overlay, setOverlay] = useState(withSubtitle ? "none" : "default");
  const [fetched, setEstimate] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState(false), [note, setNote] = useState("");
  const latest = useRef(clip);
  useEffect(() => { latest.current = clip; }, [clip]);
  const estimate = clip ? fetched : null;

  // The estimate follows the video and the choices; one request when they rest.
  const key = JSON.stringify([clip?.path, resolution, quality, overlay, withSubtitle]);
  useEffect(() => {
    if (!clip) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void apiFetch("/api/video/render-estimate", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ path: clip.path, resolution, quality, subtitle: withSubtitle, overlay }) })
        .then(r => r.json()).then((data: Estimate) => {
          setEstimate(data);
          // The server looked at the file again: keep its view, and fall back to "keep" if the resolution is no longer possible.
          if (data.files?.[0] && latest.current?.path === data.files[0].path) { setClip(data.files[0]); if (data.resolution && data.resolution !== resolution) setResolution(data.resolution); }
        }).catch(() => undefined);
    }, 400);
    return () => { controller.abort(); clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  async function pick() {
    setBusy(true); setNote("");
    try {
      const response = await apiFetch("/api/video/pick", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      if (data.files.length) { setClip(data.files[0]); if (data.files.length > 1) setNote("renderOneOnly"); }
    } catch (error) { setNote(error instanceof Error ? error.message : "VIDEO_DIALOG_FAILED"); }
    finally { setBusy(false); }
  }

  const templates = library?.templates || [];
  const first = clip, side = first && first.height && first.width && first.height > first.width ? "portrait" : "landscape";
  const defaultTemplate = templates.find(template => template.id === library?.defaults[side]);
  const noTemplate = !withSubtitle && !!library && !templates.length;
  const ready = !!clip && !clip.error && (!withSubtitle || !!file) && (withSubtitle || (overlay === "default" ? !!defaultTemplate : true)) && estimate?.enough !== false;

  async function run(event: React.FormEvent) {
    event.preventDefault(); if (!clip) return;
    setBusy(true); onMessage("");
    try {
      const video = { files: [{ path: clip.path }], resolution, quality, overlay };
      let response: Response;
      if (withSubtitle) {
        const upload = file as File;
        const params = new URLSearchParams({ tool: "subtitle_burn", name: upload.name, video: JSON.stringify(video) });
        response = await apiFetch(`/api/tools?${params}`, { method: "POST", headers: { "Content-Type": upload.type || "application/octet-stream" }, body: upload });
      } else response = await apiFetch("/api/tools", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool: "overlay", video }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.error);
      onMessage(tr("Tool run đã được thêm vào hàng đợi.")); setClip(null); setFile(null); onQueued();
    } catch (error) { onMessage(error instanceof Error ? tr(error.message) : tr("Upload thất bại.")); } finally { setBusy(false); }
  }

  const resolutions = estimate?.resolutions || ["keep"];
  return <form onSubmit={run} className="tool-form render-tool">
    <FormSection step={1} title={tr("renderVideo")} description={tr(withSubtitle ? "renderIntro8" : "renderIntro9")}>
    <div className="video-picker">
      <div className="video-picker-head">
        <button type="button" className="action-button" disabled={busy} onClick={() => void pick()}>{tr(busy ? "videoPicking" : "videoChoose")}</button>
        {clip && <button type="button" className="text-button" disabled={busy} onClick={() => setClip(null)}>{tr("videoClear")}</button>}
      </div>
      <small>{tr("renderVideoHelp")}</small>
      {clip && <p className={`render-clip${clip.error ? " video-bad" : ""}`}><span className="video-name" title={clip.path}>{clip.name}</span>{" "}
        <small>{clip.error ? tr(clip.error) : `${clip.duration_ms ? clipLength(clip.duration_ms) : "—"} · ${clip.width}×${clip.height} · ${clip.codec}`}</small></p>}
      {note && <p role="status">{tr(note)}</p>}
    </div>
    </FormSection>
    {withSubtitle && <FormSection step={2} title={tr("fkRenderSubtitle")} description={tr("renderSubtitleHelp")}>
      <FilePicker accept=".srt,.vtt" file={file} onChange={setFile} chooseLabel={t.tools.chooseFile} emptyLabel={t.tools.noFileChosen} inputLabel={tr("renderSubtitleFile")}
        rejectLabel={tr("fileWrongType", { types: "SRT, VTT" })} maxBytes={5 * 1024 ** 2} tooBigLabel={tr("fileTooBig", { size: "5 MB" })} />
    </FormSection>}
    <FormSection step={withSubtitle ? 3 : 2} title={tr("fkRenderOptions")} description={tr("fkRenderOptionsDesc")}>
    <div className="video-options">
      <label>{tr("overlayLabel")}<select value={overlay} disabled={busy || noTemplate} onChange={event => setOverlay(event.target.value)}>
        <option value="default">{defaultTemplate ? tr("overlayDefault", { name: defaultTemplate.name }) : tr("overlayDefaultNone")}</option>
        {withSubtitle && <option value="none">{tr("overlayNone")}</option>}
        {templates.map(template => <option key={template.id} value={template.id}>{template.name} · {template.orientation === "portrait" ? "9:16" : "16:9"}</option>)}
      </select></label>
      {clip && <label>{tr("videoResolution")}<select value={resolution} disabled={busy} onChange={event => setResolution(event.target.value)}>
        {["keep", "1080", "720", "480"].map(value => <option key={value} value={value} disabled={!resolutions.includes(value)}>{tr(`videoResolution.${value}`)}</option>)}</select></label>}
      {clip && <label>{tr("videoQuality")}<select value={quality} disabled={busy} onChange={event => setQuality(event.target.value)}>
        {["high", "medium", "light"].map(value => <option key={value} value={value}>{tr(`videoQuality.${value}`)}</option>)}</select></label>}
    </div>
    {noTemplate && <p className="alert" role="note">{tr("renderNoTemplate")} <Link href="/overlays">{tr("overlayManage")}</Link></p>}
    {!withSubtitle && !noTemplate && overlay === "default" && library && !defaultTemplate && <p className="alert" role="note">{tr("renderNoDefault")} <Link href="/overlays">{tr("overlayManage")}</Link></p>}
    {estimate?.plan && <p className="video-estimate" role="status">{tr("renderEstimate", { time: minutes(estimate.plan.seconds), size: gigabytes(estimate.plan.size_bytes || 0), free: gigabytes(estimate.free_bytes || 0) })}</p>}
    {estimate?.enough === false && <p className="alert" role="alert">{tr("videoDiskShort", { size: gigabytes(estimate.needed_bytes || 0) })}</p>}
    <small className="video-overlay-note">{tr("renderKeepsSound")}</small>
    </FormSection>
    <div className="fk-submit"><button disabled={busy || !allowed || !ready}>{tr(withSubtitle ? "renderRun8" : "renderRun9")}</button></div>
  </form>;
}
