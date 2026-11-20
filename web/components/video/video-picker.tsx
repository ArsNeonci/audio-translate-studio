"use client";
import { apiFetch } from "@audio/ui";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useOverlays } from "@/components/overlay/overlay-types";
import OrderedFileList from "@/components/common/ordered-file-list";
import { useLanguage } from "@/lib/i18n/language-context";

/** One clip as the local API checked it (worker/audio_translate/video/merge.py probe); `error` when it cannot be used. */
export type VideoClip = { path: string; name: string; error?: string; duration_ms?: number; width?: number; height?: number; fps?: number; codec?: string; size?: number };
/** burn: after the plain video, also make a second one with the subtitles drawn into the picture (the BURN step; re-encodes the whole video). The tick is the choice. */
/** overlay: the logo template laid on the picture: "default" (the default of the first clip's orientation), "none" or a template id; overlayName names a saved one. */
/** ultra: Ultra fast (workflow and Reprocess only): the fastest encoder setting, and with burn one pass makes the subtitled video (no BURN step, no plain video). */
export type VideoChoice = { files: VideoClip[]; resolution: string; quality: string; burn: boolean; overlay: string; overlayName?: string; ultra?: boolean };
type Estimate = { files: VideoClip[]; error?: string; resolutions?: string[]; resolution?: string; plan?: { mode: "copy" | "encode"; repeats: number | null; size_bytes: number | null; bytes_per_hour: number; voice_ms?: number | null };
  burn_plan?: { size_bytes: number | null; bytes_per_hour: number; voice_ms?: number | null; seconds_per_voice_second?: number | null } | null;
  free_bytes?: number; needed_bytes?: number | null; enough?: boolean | null };

/** Studio and Reprocess start with the subtitles drawn into the video AND Ultra fast ticked (both can be unticked). The tools start without them (see toolVideo). */
export const emptyVideo = (): VideoChoice => ({ files: [], resolution: "keep", quality: "high", burn: true, overlay: "default", ultra: true });
export const toolVideo = (): VideoChoice => ({ ...emptyVideo(), burn: false, ultra: false });
/** What the API receives: only the paths and the choices (the clips are checked again on the server). */
export const videoPayload = (choice: VideoChoice) => choice.files.length ? { files: choice.files.map(f => ({ path: f.path })), resolution: choice.resolution, quality: choice.quality,
  overlay: choice.overlay, ...(choice.burn ? { burn: true } : {}), ...(choice.ultra ? { ultra: true } : {}) } : undefined;
export const videoReady = (choice: VideoChoice) => choice.files.length > 0 && choice.files.every(f => !f.error);
/** The saved settings of a run, as a choice the picker can show. */
export const videoFromJob = (video?: { files?: VideoClip[]; resolution?: string; quality?: string; burn?: boolean; ultra?: boolean; overlay?: { id: string; name: string } | null } | null): VideoChoice =>
  video?.files?.length ? { files: video.files, resolution: video.resolution || "keep", quality: video.quality || "high", burn: !!video.burn, ultra: !!video.ultra, overlay: video.overlay?.id || "none", overlayName: video.overlay?.name } : emptyVideo();

/** A clip's length with seconds (audioDuration shows hours and minutes only, which reads 0h 00m for every clip under a minute). */
const clipLength = (ms: number) => {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
};

const minutes = (seconds: number) => seconds < 90 ? `${Math.max(1, Math.round(seconds))} s` : `${Math.round(seconds / 60)} min`;

export const gigabytes = (bytes: number) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;

/** Optional videos for Video merge: chosen with the Windows dialog (paths only), kept in order, with resolution, quality and the size estimate. */
export default function VideoPicker({ value, onChange, voiceJob, disabled, noUltra }: { value: VideoChoice; onChange: (next: VideoChoice) => void; voiceJob?: string | null; disabled?: boolean; noUltra?: boolean }) {
  const { tr } = useLanguage();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [fetched, setEstimate] = useState<Estimate | null>(null);
  const { data: library } = useOverlays();
  const estimate = value.files.length ? fetched : null;
  const latest = useRef(value);
  useEffect(() => { latest.current = value; }, [value]);

  // The estimate follows the clips, the choices and the voice; one request when they rest.
  const key = JSON.stringify([value.files.map(f => f.path), value.resolution, value.quality, voiceJob || null, value.burn, value.overlay, !!value.ultra && !noUltra]);
  useEffect(() => {
    if (!value.files.length) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void apiFetch("/api/video/estimate", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ paths: value.files.map(f => f.path), resolution: value.resolution, quality: value.quality, burn: value.burn, overlay: value.overlay, ...(value.ultra && !noUltra ? { ultra: true } : {}), ...(voiceJob ? { voice_job: voiceJob } : {}) }) })
        .then(r => r.json()).then((data: Estimate) => {
          setEstimate(data);
          const current = latest.current;
          // The server checked the clips again: keep its view of them, and fall back to Keep if the resolution is no longer possible.
          if (data.files?.length === current.files.length) onChange({ ...current, files: data.files, resolution: data.resolution || current.resolution });
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
      if (data.files.length) onChange({ ...latest.current, files: [...latest.current.files, ...data.files].slice(0, 50) });
    } catch (error) { setNote(error instanceof Error ? error.message : "VIDEO_DIALOG_FAILED"); }
    finally { setBusy(false); }
  }

  async function recheck() {
    setBusy(true); setNote("");
    try {
      const response = await apiFetch("/api/video/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths: value.files.map(f => f.path) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      onChange({ ...latest.current, files: data.files });
      setNote(data.files.some((f: VideoClip) => f.error) ? "videoRecheckBad" : "videoRecheckGood");
    } catch { setNote("VIDEO_DIALOG_FAILED"); }
    finally { setBusy(false); }
  }

  const plan = estimate?.plan;
  const burn = value.burn ? estimate?.burn_plan : null;
  const resolutions = estimate?.resolutions || ["keep"];
  // The default template is the one of the first clip's orientation; a template of a saved run that was deleted since stays chosen under its own name.
  const first = value.files[0], side = first && first.height && first.width && first.height > first.width ? "portrait" : "landscape";
  const defaultTemplate = library?.templates.find(template => template.id === library.defaults[side]);
  const chosenTemplate = value.overlay === "default" ? defaultTemplate : library?.templates.find(template => template.id === value.overlay);
  const keptOnly = value.overlay !== "default" && value.overlay !== "none" && !!library && !chosenTemplate;
  return <section className="video-picker" aria-label={tr("videoTitle")}>
    <div className="video-picker-head">
      <button type="button" className="action-button" disabled={disabled || busy || value.files.length >= 50} onClick={() => void pick()}>{tr(busy ? "videoPicking" : "videoChoose")}</button>
      {value.files.length > 0 && <button type="button" className="text-button" disabled={disabled || busy} onClick={() => void recheck()}>{tr("videoRecheck")}</button>}
      {value.files.length > 0 && <button type="button" className="text-button" disabled={disabled || busy} onClick={() => onChange({ ...value, files: [] })}>{tr("videoClear")}</button>}
    </div>
    <small>{tr("videoHelp")}</small>
    <OrderedFileList disabled={disabled} items={value.files.map((clip, index) => ({ key: `${index}:${clip.path}`, name: clip.name, title: clip.path, bad: !!clip.error,
      detail: clip.error ? tr(clip.error) : `${clip.duration_ms ? clipLength(clip.duration_ms) : "—"} · ${clip.width}×${clip.height} · ${clip.codec}` }))}
      onChange={next => { const byKey = new Map(value.files.map((clip, index) => [`${index}:${clip.path}`, clip])); onChange({ ...value, files: next.map(item => byKey.get(item.key) as VideoClip) }); }} />
    {value.files.length > 0 && <div className="video-options">
      <label>{tr("videoResolution")}<select value={value.resolution} disabled={disabled} onChange={e => onChange({ ...value, resolution: e.target.value })}>
        {["keep", "1080", "720", "480"].map(r => <option key={r} value={r} disabled={!resolutions.includes(r)}>{tr(`videoResolution.${r}`)}</option>)}
      </select></label>
      <label>{tr("overlayLabel")}<select value={value.overlay} disabled={disabled} onChange={e => onChange({ ...value, overlay: e.target.value })}>
        <option value="default">{defaultTemplate ? tr("overlayDefault", { name: defaultTemplate.name }) : tr("overlayDefaultNone")}</option>
        <option value="none">{tr("overlayNone")}</option>
        {library?.templates.map(template => <option key={template.id} value={template.id}>{template.name} · {template.orientation === "portrait" ? "9:16" : "16:9"}</option>)}
        {keptOnly && <option value={value.overlay}>{tr("overlayKept", { name: value.overlayName || value.overlay })}</option>}
      </select></label>
      {(plan?.mode === "encode" || value.burn) && <label>{tr("videoQuality")}<select value={value.quality} disabled={disabled} onChange={e => onChange({ ...value, quality: e.target.value })}>
        {["high", "medium", "light"].map(q => <option key={q} value={q}>{tr(`videoQuality.${q}`)}</option>)}
      </select></label>}
    </div>}
    {value.files.length > 0 && <small className="video-overlay-note">{(chosenTemplate || keptOnly) && <>{tr("overlayEncode")}{" "}</>}<Link href="/overlays">{tr("overlayManage")}</Link></small>}
    {value.files.length > 0 && <div className="video-burn">
      <label className="auto-tts-toggle"><input type="checkbox" checked={value.burn} disabled={disabled} onChange={e => onChange({ ...value, burn: e.target.checked })} />
        <span>{tr("burnLabel")}</span><small>{tr(value.ultra && !noUltra ? "burnHelpUltra" : "burnHelp")}</small></label>
      {!noUltra && <>
        <label className="auto-tts-toggle"><input type="checkbox" checked={!!value.ultra} disabled={disabled} onChange={e => onChange({ ...value, ultra: e.target.checked })} />
          <span>{tr("ultraLabel")}</span><small>{tr("ultraHelp")}</small></label>
      </>}
      {value.burn && <p className="alert" role="note">{burn?.seconds_per_voice_second && burn.voice_ms ? tr(value.ultra && !noUltra ? "ultraWarnTime" : "burnWarnTime", { time: minutes(burn.voice_ms / 1000 * burn.seconds_per_voice_second) }) : tr(value.ultra && !noUltra ? "ultraWarn" : "burnWarn", { slow: burn?.seconds_per_voice_second ? Math.round(burn.seconds_per_voice_second * 60) : 8 })}</p>}
    </div>}
    {plan && !(value.ultra && value.burn && burn && !noUltra) && <p className="video-estimate" role="status">
      {plan.size_bytes != null ? tr("videoSize", { size: gigabytes(plan.size_bytes), free: gigabytes(estimate?.free_bytes || 0) }) : tr("videoSizePerHour", { size: gigabytes(plan.bytes_per_hour), free: gigabytes(estimate?.free_bytes || 0) })}
      {" · "}{tr(plan.mode === "copy" ? "videoCopy" : "videoEncode")}
      {plan.repeats != null && <>{" · "}{plan.repeats > 1 ? tr("videoRepeats", { count: plan.repeats }) : tr("videoCut")}</>}
    </p>}
    {burn && <p className="video-estimate" role="status">{tr(value.ultra && !noUltra ? "videoUltraPlan" : "videoBurnPlan")}{burn.size_bytes != null ? ` · ${tr(value.ultra && !noUltra ? "videoUltraSize" : "videoBurnSize", { size: gigabytes(burn.size_bytes) })}` : value.ultra && !noUltra ? ` · ${tr("videoSizePerHour", { size: gigabytes(burn.bytes_per_hour), free: gigabytes(estimate?.free_bytes || 0) })}` : ""}</p>}
    {estimate?.enough === false && <p className="alert" role="alert">{tr("videoDiskShort", { size: gigabytes(estimate.needed_bytes || 0) })}</p>}
    {note && <p role="status">{tr(note)}</p>}
  </section>;
}

/** The finished video of a run: a preview and the buttons to open it or its folder. */
export function VideoResult({ id, scope, url, subtitled }: { id: string; scope: "workflows" | "tools"; url: string; subtitled?: boolean }) {
  const { tr } = useLanguage();
  const [note, setNote] = useState("");
  async function open(target: "video" | "folder") {
    setNote("");
    try {
      const response = await apiFetch("/api/video/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, scope, target: subtitled ? `subtitled${target === "folder" ? "-folder" : ""}` : target }) });
      if (!response.ok) throw new Error((await response.json()).error);
    } catch (error) { setNote(error instanceof Error ? error.message : "VIDEO_NOT_READY"); }
  }
  return <div className="video-result">
    <video controls preload="metadata" src={url} aria-label={tr(subtitled ? "VIDEO_SUB_MP4" : "VIDEO_MP4")} />
    <div className="video-result-actions">
      <button type="button" className="action-button" onClick={() => void open("video")}>{tr("videoOpen")}</button>
      <button type="button" className="text-button" onClick={() => void open("folder")}>{tr("videoOpenFolder")}</button>
    </div>
    {note && <p className="alert" role="alert">{tr(note)}</p>}
  </div>;
}

/** Opens a video that finished while the app window is open (minimised counts as open), once: the API keeps a marker per finished video. */
export function useVideoAutoOpen() {
  useEffect(() => {
    const tick = () => void apiFetch("/api/video/auto-open", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => undefined);
    const timer = setInterval(tick, 4000);
    return () => clearInterval(timer);
  }, []);
}
