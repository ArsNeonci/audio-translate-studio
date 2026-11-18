"use client";
import { apiFetch, FilePicker } from "@audio/ui";
import { useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import type { Job, Step } from "@/lib/shared/job-types";

/** The stages that can start from a file, and the stage whose result that file is (worker/audio_translate/workflow/imports.py). */
export const IMPORT_STEPS = ["TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"] as const;
export type ImportStep = (typeof IMPORT_STEPS)[number];
export const isImportStep = (step: string): step is ImportStep => (IMPORT_STEPS as readonly string[]).includes(step);
const AUDIO_FILES = ".wav,.mp3,.m4a,.flac,.ogg,.aac,.webm,.mp4", TEXT_FILES = ".txt,.md,.jsonl";
const ORDER: Step[] = ["DOWNLOAD", "TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"];

export type ImportChoice = { mode: "existing" | "file"; importId: string | null; name: string };
export const noImport = (mode: ImportChoice["mode"] = "existing"): ImportChoice => ({ mode, importId: null, name: "" });
type Report = { mode: string; found?: number; rows?: number; duration_ms?: number; missing?: number[]; duplicate?: number[]; unknown?: number[]; empty?: number[]; dropped_lines?: number;
  han_paragraphs?: number; estimated_time?: boolean; out_of_order?: boolean; blocked?: string[]; preview?: { n: number; zh: string; vi: string }[] };

const list = (numbers: number[]) => numbers.slice(0, 20).join(", ") + (numbers.length > 20 ? "…" : "");
const clock = (ms: number) => { const s = Math.round(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

/** Reprocess: choose between the result the run already has and a file the person loads. The file is checked on the server as soon as it is chosen
 *  and nothing of the run changes until Reprocess is pressed with the import_id this panel reports. */
export default function ImportPanel({ job, step, value, onChange, disabled }: { job: Job; step: ImportStep; value: ImportChoice; onChange: (next: ImportChoice) => void; disabled?: boolean }) {
  const { t, tr } = useLanguage();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const audio = step === "TRANSCRIPTION";
  const accept = audio ? AUDIO_FILES : TEXT_FILES;
  const names = accept.split(",").map(item => item.slice(1).toUpperCase()).join(", ");
  const before = ORDER.slice(0, ORDER.indexOf(step));
  const skipped = before.slice(0, -1).filter(item => job.steps?.[item]?.state !== "COMPLETED");
  const earlierDone = before.every(item => job.steps?.[item]?.state === "COMPLETED");

  async function choose(next: File | null) {
    setFile(next); setReport(null); setError(""); onChange({ ...value, importId: null, name: next?.name || "" });
    if (!next) return;
    setChecking(true);
    try {
      const params = new URLSearchParams({ step, name: next.name });
      const response = await apiFetch(`/api/jobs/${job.id}/import?${params}`, { method: "POST", headers: { "Content-Type": next.type || "application/octet-stream" }, body: next });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      setReport(data.report);
      onChange({ mode: "file", importId: data.import_id, name: next.name });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "X901"); }
    finally { setChecking(false); }
  }

  const modes: ImportChoice["mode"][] = ["existing", "file"];
  return <section className="import-panel" aria-label={tr("importTitle")}>
    <strong>{tr("importTitle")}</strong>
    <div className="source-options" role="radiogroup" aria-label={tr("importTitle")}>{modes.map(mode =>
      <button key={mode} type="button" role="radio" aria-checked={value.mode === mode} disabled={disabled || (mode === "existing" && !earlierDone)}
        className={`source-chip${value.mode === mode ? " selected" : ""}`} onClick={() => { if (mode === "existing") { setFile(null); setReport(null); setError(""); } onChange(noImport(mode)); }}>
        {tr(mode === "existing" ? "importUseExisting" : "importLoad")}</button>)}</div>
    {value.mode === "file" && <>
      <small>{tr(`importHelp.${step}`)}</small>
      <FilePicker accept={accept} file={file} onChange={next => void choose(next)} chooseLabel={t.tools.chooseFile} emptyLabel={t.tools.noFileChosen} inputLabel={t.tools.inputFile}
        rejectLabel={tr("fileWrongType", { types: names })} maxBytes={audio ? 2 * 1024 ** 3 : 64 * 1024 ** 2} tooBigLabel={tr("fileTooBig", { size: audio ? "2 GB" : "64 MB" })} />
      {checking && <p role="status">{tr("importChecking")}</p>}
      {error && <p className="alert" role="alert">{tr(error)}</p>}
      {report && !report.blocked?.length && <p className="import-ok" role="status">{report.mode === "audio" ? tr("importOkAudio", { time: clock(report.duration_ms || 0) }) : tr("importOkText", { found: report.found ?? report.rows ?? 0 })}</p>}
      {!!report?.blocked?.length && <div className="alert" role="alert"><strong>{tr("importBlocked")}</strong>
        <ul>{report.blocked.map(reason => <li key={reason}>{tr(reason)}</li>)}
          {!!report.missing?.length && <li>{tr("importMissing", { list: list(report.missing) })}</li>}
          {!!report.unknown?.length && <li>{tr("importUnknown", { list: list(report.unknown) })}</li>}
          {!!report.empty?.length && <li>{tr("importEmpty", { list: list(report.empty) })}</li>}</ul></div>}
      {report && <ul className="import-notes">
        {!!report.duplicate?.length && <li>{tr("importDuplicate", { list: list(report.duplicate) })}</li>}
        {!!report.han_paragraphs && <li>{tr("importHan", { count: report.han_paragraphs })}</li>}
        {!!report.dropped_lines && <li>{tr("importDropped", { count: report.dropped_lines })}</li>}
        {report.estimated_time && <li>{tr("importEstimated")}</li>}
        {report.out_of_order && <li>{tr("importOutOfOrder")}</li>}
      </ul>}
      {!!report?.preview?.length && <table className="import-preview"><caption>{tr("importPreview")}</caption><tbody>
        {report.preview.map(item => <tr key={item.n}><td>[{item.n}]</td>{item.zh && <td lang="zh">{item.zh}</td>}<td>{item.vi}</td></tr>)}</tbody></table>}
      {value.importId && !!skipped.length && <small>{tr("importSkips", { steps: skipped.map(item => tr(item)).join(", ") })}</small>}
    </>}
  </section>;
}
