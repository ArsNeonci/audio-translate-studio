"use client";
import { apiFetch } from "@audio/ui";
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import { audioDuration } from "@/lib/shared/format";

/** One clip as the local API checked it (worker/audio_translate/video/merge.py probe); `error` when it cannot be used. */
export type VideoClip = { path: string; name: string; error?: string; duration_ms?: number; width?: number; height?: number; fps?: number; codec?: string; size?: number };
/** burn: after the plain video, also make a second one with the subtitles drawn into the picture (the BURN step; re-encodes the whole video). The tick is the choice. */
export type VideoChoice = { files: VideoClip[]; resolution: string; quality: string; burn: boolean };
type Estimate = { files: VideoClip[]; error?: string; resolutions?: string[]; resolution?: string; plan?: { mode: "copy" | "encode"; repeats: number | null; size_bytes: number | null; bytes_per_hour: number; voice_ms?: number | null };
  burn_plan?: { size_bytes: number | null; bytes_per_hour: number; voice_ms?: number | null; seconds_per_voice_second?: number | null } | null;
  free_bytes?: number; needed_bytes?: number | null; enough?: boolean | null };

export const emptyVideo = (): VideoChoice => ({ files: [], resolution: "keep", quality: "high", burn: false });
/** What the API receives: only the paths and the choices (the clips are checked again on the server). */
export const videoPayload = (choice: VideoChoice) => choice.files.length ? { files: choice.files.map(f => ({ path: f.path })), resolution: choice.resolution, quality: choice.quality,
  ...(choice.burn ? { burn: true } : {}) } : undefined;
export const videoReady = (choice: VideoChoice) => choice.files.length > 0 && choice.files.every(f => !f.error);
/** The saved settings of a run, as a choice the picker can show. */
export const videoFromJob = (video?: { files?: VideoClip[]; resolution?: string; quality?: string; burn?: boolean } | null): VideoChoice =>
  video?.files?.length ? { files: video.files, resolution: video.resolution || "keep", quality: video.quality || "high", burn: !!video.burn } : emptyVideo();

const minutes = (seconds: number) => seconds < 90 ? `${Math.max(1, Math.round(seconds))} s` : `${Math.round(seconds / 60)} min`;

export const gigabytes = (bytes: number) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;

/** Optional videos for Video merge: chosen with the Windows dialog (paths only), kept in order, with resolution, quality and the size estimate. */
export default function VideoPicker({ value, onChange, voiceJob, disabled }: { value: VideoChoice; onChange: (next: VideoChoice) => void; voiceJob?: string | null; disabled?: boolean }) {
  const { tr } = useLanguage();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [fetched, setEstimate] = useState<Estimate | null>(null);
  const estimate = value.files.length ? fetched : null;
  const latest = useRef(value);
  useEffect(() => { latest.current = value; }, [value]);

  // The estimate follows the clips, the choices and the voice; one request when they rest.
  const key = JSON.stringify([value.files.map(f => f.path), value.resolution, value.quality, voiceJob || null, value.burn]);
  useEffect(() => {
    if (!value.files.length) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void apiFetch("/api/video/estimate", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ paths: value.files.map(f => f.path), resolution: value.resolution, quality: value.quality, burn: value.burn, ...(voiceJob ? { voice_job: voiceJob } : {}) }) })
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

  const move = (index: number, by: number) => {
    const files = [...value.files]; const [item] = files.splice(index, 1); files.splice(index + by, 0, item); onChange({ ...value, files });
  };
  const remove = (index: number) => onChange({ ...value, files: value.files.filter((_, i) => i !== index) });
  const plan = estimate?.plan;
  const burn = value.burn ? estimate?.burn_plan : null;
  const resolutions = estimate?.resolutions || ["keep"];
  return <section className="video-picker" aria-label={tr("videoTitle")}>
    <div className="video-picker-head">
      <strong>{tr("videoTitle")}</strong>
      <button type="button" className="action-button" disabled={disabled || busy || value.files.length >= 50} onClick={() => void pick()}>{tr(busy ? "videoPicking" : "videoChoose")}</button>
      {value.files.length > 0 && <button type="button" className="text-button" disabled={disabled || busy} onClick={() => void recheck()}>{tr("videoRecheck")}</button>}
      {value.files.length > 0 && <button type="button" className="text-button" disabled={disabled || busy} onClick={() => onChange({ ...value, files: [] })}>{tr("videoClear")}</button>}
    </div>
    <small>{tr("videoHelp")}</small>
    {value.files.length > 0 && <ol className="video-list">{value.files.map((clip, index) => <li key={`${clip.path}-${index}`} className={clip.error ? "video-bad" : undefined}>
      <span className="video-name" title={clip.path}>{clip.name}</span>
      <small>{clip.error ? tr(clip.error) : `${audioDuration(clip.duration_ms || 0)} · ${clip.width}×${clip.height} · ${clip.codec}`}</small>
      <span className="video-actions">
        <button type="button" className="text-button" aria-label={tr("videoUp")} title={tr("videoUp")} disabled={disabled || index === 0} onClick={() => move(index, -1)}>↑</button>
        <button type="button" className="text-button" aria-label={tr("videoDown")} title={tr("videoDown")} disabled={disabled || index === value.files.length - 1} onClick={() => move(index, 1)}>↓</button>
        <button type="button" className="text-button" aria-label={tr("videoRemove")} title={tr("videoRemove")} disabled={disabled} onClick={() => remove(index)}>✕</button>
      </span>
    </li>)}</ol>}
    {value.files.length > 0 && <div className="video-options">
      <label>{tr("videoResolution")}<select value={value.resolution} disabled={disabled} onChange={e => onChange({ ...value, resolution: e.target.value })}>
        {["keep", "1080", "720", "480"].map(r => <option key={r} value={r} disabled={!resolutions.includes(r)}>{tr(`videoResolution.${r}`)}</option>)}
      </select></label>
      {(plan?.mode === "encode" || value.burn) && <label>{tr("videoQuality")}<select value={value.quality} disabled={disabled} onChange={e => onChange({ ...value, quality: e.target.value })}>
        {["high", "medium", "light"].map(q => <option key={q} value={q}>{tr(`videoQuality.${q}`)}</option>)}
      </select></label>}
    </div>}
    {value.files.length > 0 && <div className="video-burn">
      <label className="auto-tts-toggle"><input type="checkbox" checked={value.burn} disabled={disabled} onChange={e => onChange({ ...value, burn: e.target.checked })} />
        <span>{tr("burnLabel")}</span><small>{tr("burnHelp")}</small></label>
      {value.burn && <p className="alert" role="note">{burn?.seconds_per_voice_second && burn.voice_ms ? tr("burnWarnTime", { time: minutes(burn.voice_ms / 1000 * burn.seconds_per_voice_second) }) : tr("burnWarn", { slow: burn?.seconds_per_voice_second ? Math.round(burn.seconds_per_voice_second * 60) : 8 })}</p>}
    </div>}
    {plan && <p className="video-estimate" role="status">
      {plan.size_bytes != null ? tr("videoSize", { size: gigabytes(plan.size_bytes), free: gigabytes(estimate?.free_bytes || 0) }) : tr("videoSizePerHour", { size: gigabytes(plan.bytes_per_hour), free: gigabytes(estimate?.free_bytes || 0) })}
      {" · "}{tr(plan.mode === "copy" ? "videoCopy" : "videoEncode")}
      {plan.repeats != null && <>{" · "}{plan.repeats > 1 ? tr("videoRepeats", { count: plan.repeats }) : tr("videoCut")}</>}
    </p>}
    {burn && <p className="video-estimate" role="status">{tr("videoBurnPlan")}{burn.size_bytes != null ? ` · ${tr("videoBurnSize", { size: gigabytes(burn.size_bytes) })}` : ""}</p>}
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
