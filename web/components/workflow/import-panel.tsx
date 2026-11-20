"use client";
import { apiFetch, FilePicker } from "@audio/ui";
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import FormSection from "@/components/common/form-section";
import OrderedFileList, { byName, type OrderedFile } from "@/components/common/ordered-file-list";
import type { Job, Step } from "@/lib/shared/job-types";

/** The stages that can start from a file, and the stage whose result that file is (worker/audio_translate/workflow/imports.py). */
export const IMPORT_STEPS = ["TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"] as const;
export type ImportStep = (typeof IMPORT_STEPS)[number];
export const isImportStep = (step: string): step is ImportStep => (IMPORT_STEPS as readonly string[]).includes(step);
/** The stages whose file may come in several parts (the translation of each part of tool 7): several files, in an order the person sets. */
const MULTI: ImportStep[] = ["MODERATION", "TTS"];
const AUDIO_FILES = ".wav,.mp3,.m4a,.flac,.ogg,.aac,.webm,.mp4", TEXT_FILES = ".txt,.md,.jsonl";
const ORDER: Step[] = ["DOWNLOAD", "TRANSCRIPTION", "TRANSLATION", "MODERATION", "TTS"];
const MAX_FILES = 500, MAX_BYTES = 64 * 1024 ** 2;

export type ImportChoice = { mode: "existing" | "file"; importId: string | null; name: string };
export const noImport = (mode: ImportChoice["mode"] = "existing"): ImportChoice => ({ mode, importId: null, name: "" });
type PartReport = { id: number; name: string; first: number | null; last: number | null; count: number; dropped_lines: number; han: boolean; empty: boolean; repeats: number[]; repeats_of: string[] };
type Report = { mode: string; found?: number; rows?: number; duration_ms?: number; missing?: number[]; duplicate?: number[]; unknown?: number[]; empty?: number[]; dropped_lines?: number;
  han_paragraphs?: number; estimated_time?: boolean; out_of_order?: boolean; blocked?: string[]; preview?: { n: number; zh: string; vi: string }[]; parts?: PartReport[] };
type Reply = { import_id: string; report: Report; ready?: boolean; part?: { id: number } };
/** A file of the list: the browser's File until it is sent, then the id the draft gave it. */
type Entry = { key: string; file: File; part?: number };

const list = (numbers: number[]) => numbers.slice(0, 20).join(", ") + (numbers.length > 20 ? "…" : "");
const clock = (ms: number) => { const s = Math.round(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const extension = (name: string) => name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "";

/** Reprocess: the result the run already has, or a file the person loads (several, in order, for a translation made part by part). Each file is
 *  checked on the server as soon as it is chosen; nothing of the run changes until Reprocess is pressed with the import_id this panel reports. */
export default function ImportPanel({ job, step, value, onChange, disabled, stepNo }: { job: Job; step: ImportStep; value: ImportChoice; onChange: (next: ImportChoice) => void; disabled?: boolean; stepNo?: number }) {
  const { t, tr } = useLanguage();
  const multi = MULTI.includes(step);
  const [file, setFile] = useState<File | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const counter = useRef(0);
  const audio = step === "TRANSCRIPTION";
  const accept = audio ? AUDIO_FILES : TEXT_FILES;
  const names = accept.split(",").map(item => item.slice(1).toUpperCase()).join(", ");
  const before = ORDER.slice(0, ORDER.indexOf(step));
  const skipped = before.slice(0, -1).filter(item => job.steps?.[item]?.state !== "COMPLETED");
  const earlierDone = before.every(item => job.steps?.[item]?.state === "COMPLETED");

  async function send(path: string, init: RequestInit): Promise<Reply> {
    const response = await apiFetch(path, init);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "X901");
    return data;
  }
  const upload = (target: File, path: string) => send(path, { method: "POST", headers: { "Content-Type": target.type || "application/octet-stream" }, body: target });
  const settle = (data: Reply, name: string) => { setReport(data.report); onChange({ mode: "file", importId: data.ready === false ? null : data.import_id, name }); };

  /** One file (audio, Chinese text): the old single-file check. */
  async function chooseOne(next: File | null) {
    setFile(next); setReport(null); setError(""); onChange({ ...value, importId: null, name: next?.name || "" });
    if (!next) return;
    setChecking(true);
    try { settle(await upload(next, `/api/jobs/${job.id}/import?${new URLSearchParams({ step, name: next.name })}`), next.name); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "X901"); }
    finally { setChecking(false); }
  }

  /** Several files: the new ones are sent (the first starts a draft), then the whole list is checked in its order. */
  async function sync(list: Entry[]) {
    setError(""); onChange({ ...value, mode: "file", importId: null, name: list.map(entry => entry.file.name).join(", ") });
    if (!list.length) { setDraft(null); setReport(null); return; }
    setChecking(true);
    try {
      let id = draft, latest: Reply | null = null;
      const sent = [...list];
      for (let index = 0; index < sent.length; index++) {
        const entry = sent[index];
        if (entry.part) continue;
        if (!id) {
          latest = await upload(entry.file, `/api/jobs/${job.id}/import?${new URLSearchParams({ step, name: entry.file.name })}`);
          id = latest.import_id; sent[index] = { ...entry, part: 1 }; setDraft(id);
        } else {
          const reply = await upload(entry.file, `/api/jobs/${job.id}/import/${id}/parts?${new URLSearchParams({ name: entry.file.name })}`);
          sent[index] = { ...entry, part: reply.part?.id };
        }
      }
      setEntries(sent);
      const order = sent.map(entry => entry.part as number);
      // A draft that was started with this very list (one file) needs no second check.
      if (!(latest && order.length === 1)) latest = await send(`/api/jobs/${job.id}/import/${id}/check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order }) });
      settle(latest, sent.map(entry => entry.file.name).join(", "));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "X901"); }
    finally { setChecking(false); }
  }

  // A change of order or a removed file is checked again when the list rests.
  const orderKey = entries.map(entry => entry.key).join("|");
  const pending = useRef(false);
  useEffect(() => {
    if (!pending.current) return;
    pending.current = false;
    const timer = setTimeout(() => void sync(entries), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderKey]);

  function add(files: FileList | File[] | null) {
    const chosen = Array.from(files || []);   // copied first: the input's FileList empties when its value is reset
    if (picker.current) picker.current.value = "";
    if (!chosen.length) return;
    const wrong = chosen.filter(item => !TEXT_FILES.split(",").includes(extension(item.name)));
    const fitting = chosen.filter(item => !wrong.includes(item)).sort((a, b) => byName(a.name, b.name));
    const total = [...entries.map(entry => entry.file), ...fitting].reduce((sum, item) => sum + item.size, 0);
    if (wrong.length) setError(tr("fileWrongType", { types: names }));
    if (entries.length + fitting.length > MAX_FILES) { setError("Too many files; load at most 500"); return; }
    if (total > MAX_BYTES) { setError(tr("fileTooBig", { size: "64 MB" })); return; }
    if (!fitting.length) return;
    const next = [...entries, ...fitting.map(item => ({ key: `f${++counter.current}`, file: item }))];
    setEntries(next); void sync(next);
  }

  function reorder(next: OrderedFile[]) {
    const byKey = new Map(entries.map(entry => [entry.key, entry]));
    pending.current = true;
    setEntries(next.map(item => byKey.get(item.key) as Entry));
  }

  function sortByName() { pending.current = true; setEntries([...entries].sort((a, b) => byName(a.file.name, b.file.name))); }
  function clearAll() { setEntries([]); setDraft(null); setReport(null); setError(""); onChange({ mode: "file", importId: null, name: "" }); }

  const partInfo = (entry: Entry) => report?.parts?.find(part => part.id === entry.part);
  const detail = (entry: Entry) => {
    const part = partInfo(entry);
    const size = entry.file.size < 1048576 ? `${Math.max(1, Math.round(entry.file.size / 1024))} KB` : `${(entry.file.size / 1048576).toFixed(1)} MB`;
    if (!part) return checking ? `${size} · ${tr("importChecking")}` : size;
    const notes = [size, part.count ? tr("importPartRange", { first: part.first ?? 0, last: part.last ?? 0, count: part.count }) : part.empty ? tr("importPartEmpty") : tr("importPartNoNumbers")];
    if (part.repeats.length) notes.push(tr("importPartRepeats", { list: list(part.repeats), names: part.repeats_of.join(", ") }));
    if (part.dropped_lines) notes.push(tr("importDropped", { count: part.dropped_lines }));
    if (part.han) notes.push(tr("importPartHan"));
    return notes.join(" · ");
  };
  const partBad = (entry: Entry) => { const part = partInfo(entry); return !!part && (part.repeats.length > 0 || part.empty || (!part.count && !!report?.parts?.some(other => other.count))); };

  const modes: ImportChoice["mode"][] = ["existing", "file"];
  return <FormSection step={stepNo} title={tr("importTitle")} description={tr("fkImportDesc")}><div className="import-panel">
    <div className="source-options" role="radiogroup" aria-label={tr("importTitle")}>{modes.map(mode =>
      <button key={mode} type="button" role="radio" aria-checked={value.mode === mode} disabled={disabled || (mode === "existing" && !earlierDone)}
        className={`source-chip${value.mode === mode ? " selected" : ""}`} onClick={() => { if (mode === "existing") { setFile(null); clearAll(); } onChange(noImport(mode)); }}>
        {tr(mode === "existing" ? "importUseExisting" : "importLoad")}</button>)}</div>
    {value.mode === "file" && <>
      <small>{tr(`importHelp.${step}`)}</small>
      {multi ? <div className={`import-drop${dragging ? " dragging" : ""}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
        onDrop={event => { event.preventDefault(); setDragging(false); if (!disabled) add(event.dataTransfer.files); }}>
        <div className="video-picker-head">
          <button type="button" className="action-button" disabled={disabled || checking} onClick={() => picker.current?.click()}>{tr(entries.length ? "importAddFiles" : "importChooseFiles")}</button>
          {entries.length > 1 && <button type="button" className="text-button" disabled={disabled || checking} onClick={sortByName}>{tr("importSortByName")}</button>}
          {entries.length > 0 && <button type="button" className="text-button" disabled={disabled || checking} onClick={clearAll}>{tr("importClearFiles")}</button>}
          <input ref={picker} type="file" multiple hidden accept={TEXT_FILES} aria-label={t.tools.inputFile} onChange={event => add(event.target.files)} />
        </div>
        <small>{tr("importMultiHelp")}</small>
        <OrderedFileList disabled={disabled || checking} onChange={reorder}
          items={entries.map(entry => ({ key: entry.key, name: entry.file.name, detail: detail(entry), bad: partBad(entry) }))} />
      </div> : <FilePicker accept={accept} file={file} onChange={next => void chooseOne(next)} chooseLabel={t.tools.chooseFile} emptyLabel={t.tools.noFileChosen} inputLabel={t.tools.inputFile}
        rejectLabel={tr("fileWrongType", { types: names })} maxBytes={audio ? 2 * 1024 ** 3 : MAX_BYTES} tooBigLabel={tr("fileTooBig", { size: audio ? "2 GB" : "64 MB" })} />}
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
        {!multi && !!report.dropped_lines && <li>{tr("importDropped", { count: report.dropped_lines })}</li>}
        {report.estimated_time && <li>{tr("importEstimated")}</li>}
        {report.out_of_order && <li>{tr("importOutOfOrder")}</li>}
      </ul>}
      {!!report?.preview?.length && <table className="import-preview"><caption>{tr("importPreview")}</caption><tbody>
        {report.preview.map(item => <tr key={item.n}><td>[{item.n}]</td>{item.zh && <td lang="zh">{item.zh}</td>}<td>{item.vi}</td></tr>)}</tbody></table>}
      {value.importId && !!skipped.length && <small>{tr("importSkips", { steps: skipped.map(item => tr(item)).join(", ") })}</small>}
    </>}
  </div></FormSection>;
}
