"use client";
import { apiFetch, FilePicker } from "@audio/ui";
import { useEffect, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import { runNumber } from "@/lib/shared/format";
import FormSection from "@/components/common/form-section";

type Source = { job_id: string; scope: "workflows" | "tools"; workflow_no: number | null; name: string; created_at: string; chars: number };
const LIMITS = { min: 500, max: 20000, standard: 3000 };
const TEXT_FILES = ".txt,.md,.jsonl";

/** Tool 7: the Chinese text of a finished run (or a text file) cut into small numbered files for the person's own chatbot. */
export default function SplitTool({ allowed, initialSource, onQueued, onMessage }: { allowed: boolean; initialSource?: string; onQueued: () => void; onMessage: (text: string) => void }) {
  const { t, tr } = useLanguage();
  const [sources, setSources] = useState<Source[]>([]);
  const [from, setFrom] = useState<"run" | "file">("run");
  const [sourceJob, setSourceJob] = useState(initialSource || "");
  const [file, setFile] = useState<File | null>(null);
  const [size, setSize] = useState(LIMITS.standard);
  const [prompt, setPrompt] = useState(true);
  const [edited, setEdited] = useState<string | null>(null);   // the person's own wording; until then the box shows the default in the current language
  const [busy, setBusy] = useState(false);
  useEffect(() => { void apiFetch("/api/split/sources", { cache: "no-store" }).then(r => r.json()).then(d => setSources(d.sources || [])).catch(() => undefined); }, []);
  // The last run's settings come back (they are also what a workflow translated by hand cuts its text with).
  useEffect(() => { void apiFetch("/api/split/settings", { cache: "no-store" }).then(r => r.json()).then(d => { if (Number.isInteger(d.max_chars)) setSize(d.max_chars); if (typeof d.prompt === "boolean") setPrompt(d.prompt); }).catch(() => undefined); }, []);

  const sizeOk = Number.isInteger(size) && size >= LIMITS.min && size <= LIMITS.max;
  const text = edited ?? tr("splitPromptDefault");
  const chosen = sources.find(item => item.job_id === sourceJob);
  const chars = from === "run" ? chosen?.chars : file ? Math.round(file.size / 3) : undefined;   // a Chinese character is 3 bytes in UTF-8
  const parts = chars && sizeOk ? Math.max(1, Math.ceil(chars * 1.04 / size)) : null;
  const ready = sizeOk && (from === "run" ? !!sourceJob : !!file);

  async function run(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); onMessage("");
    try {
      const split = { max_chars: size, prompt, prompt_text: prompt ? text : "" };
      let response: Response;
      if (from === "run") response = await apiFetch("/api/tools", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool: "split", source_job: sourceJob, split }) });
      else {
        const upload = file as File;
        const params = new URLSearchParams({ tool: "split", name: upload.name, max_chars: String(size), prompt: prompt ? "1" : "0", ...(prompt ? { prompt_text: text } : {}) });
        response = await apiFetch(`/api/tools?${params}`, { method: "POST", headers: { "Content-Type": upload.type || "application/octet-stream" }, body: upload });
      }
      const data = await response.json(); if (!response.ok) throw new Error(data.error);
      onMessage(tr("Tool run đã được thêm vào hàng đợi.")); setFile(null); onQueued();
    } catch (error) { onMessage(error instanceof Error ? tr(error.message) : tr("Upload thất bại.")); } finally { setBusy(false); }
  }

  return <form onSubmit={run} className="tool-form split-tool">
    <FormSection step={1} title={tr("splitSource")} description={tr("splitIntro")}>
    <div className="source-options" role="radiogroup" aria-label={tr("splitSource")}>{(["run", "file"] as const).map(value =>
      <button key={value} type="button" role="radio" aria-checked={from === value} className={`source-chip${from === value ? " selected" : ""}`} onClick={() => setFrom(value)}>{tr(value === "run" ? "splitFromRun" : "splitFromFile")}</button>)}</div>
    {from === "run"
      ? <label>{tr("splitSource")}<select value={sourceJob} required onChange={event => setSourceJob(event.target.value)}>
        <option value="">{tr(sources.length ? "splitChoose" : "splitNone")}</option>
        {sources.map(item => <option key={item.job_id} value={item.job_id}>{tr(item.scope === "tools" ? "Tool #" : "Workflow #")}{runNumber(item.workflow_no ?? undefined)} · {item.name}</option>)}
      </select></label>
      : <FilePicker accept={TEXT_FILES} file={file} onChange={setFile} chooseLabel={t.tools.chooseFile} emptyLabel={t.tools.noFileChosen} inputLabel={t.tools.inputFile}
        rejectLabel={tr("fileWrongType", { types: "TXT, MD, JSONL" })} maxBytes={64 * 1024 ** 2} tooBigLabel={tr("fileTooBig", { size: "64 MB" })} />}
    </FormSection>
    <FormSection step={2} title={tr("fkSplitParts")} description={tr("fkSplitPartsDesc")}>
      <label>{tr("splitSize")}
        <input type="number" inputMode="numeric" min={LIMITS.min} max={LIMITS.max} step={100} value={size} disabled={busy} onChange={event => setSize(Number(event.target.value))} />
      </label>
      <small>{tr("splitSizeHelp", { min: LIMITS.min, max: LIMITS.max.toLocaleString() })}{parts ? ` ${tr("splitEstimate", { count: parts })}` : ""}</small>
      {!sizeOk && <small role="alert" className="video-bad">{tr("Invalid part size")}</small>}
    </FormSection>
    <FormSection step={3} title={tr("fkSplitPrompt")}>
      <label className="auto-tts-toggle"><input type="checkbox" checked={prompt} disabled={busy} onChange={event => setPrompt(event.target.checked)} />
        <span>{tr("splitPrompt")}</span><small>{tr("splitPromptHelp")}</small></label>
      {prompt && <label className="split-prompt">{tr("splitPromptText")}
        <textarea rows={4} maxLength={2000} value={text} disabled={busy} onChange={event => setEdited(event.target.value)} /></label>}
    </FormSection>
    <div className="fk-submit"><button disabled={busy || !allowed || !ready}>{tr("splitRun")}</button></div>
  </form>;
}
