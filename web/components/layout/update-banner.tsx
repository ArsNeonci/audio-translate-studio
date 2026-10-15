"use client";
import { apiFetch } from "@audio/ui";
import { useCallback, useEffect, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";

export type UpdateState = {
  installed: { version: string | null; product: string | null; runtime: string | null; can_update: boolean };
  channel: string;
  offer: { version: string; serial: number; notes: Record<string, string>; kind: "app" | "installer"; size: number; required: boolean; failed_before: boolean; downgrade: boolean } | null;
  download: { state: "idle" | "downloading" | "ready" | "failed"; done: number; total: number; error: string | null; version: string | null };
  ready: boolean;
  checked_at: number | null;
  error: string | null;
  last_result: { ok: boolean; version: string; from: string; error: string } | null;
};

const megabytes = (bytes: number) => `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;

/** The state of app updates, polled: slowly while idle, fast while a package is downloading. */
export function useUpdate() {
  const [state, setState] = useState<UpdateState | null>(null);
  const read = useCallback(async () => {
    try { setState((await (await apiFetch("/api/update", { cache: "no-store" })).json()) as UpdateState); } catch { /* the app is restarting */ }
  }, []);
  const downloading = state?.download.state === "downloading";
  useEffect(() => {
    const first = setTimeout(() => void read(), 0);
    const timer = setInterval(() => void read(), downloading ? 1000 : 15000);
    return () => { clearTimeout(first); clearInterval(timer); };
  }, [read, downloading]);
  return { state, setState, read };
}

export async function updateCall(path: string, body: unknown = {}) {
  const response = await apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { ok: response.ok, status: response.status, data: await response.json().catch(() => ({})) };
}

/** Start the download, or install the downloaded release. Asks first when workflows are running. */
export function useUpdateActions(onChange: () => void) {
  const { tr } = useLanguage();
  const [applying, setApplying] = useState(false);
  const [problem, setProblem] = useState("");
  const download = async () => { setProblem(""); const r = await updateCall("/api/update/download"); if (!r.ok) setProblem(r.data.error || "UPDATE_FAILED"); onChange(); };
  const apply = async () => {
    setProblem("");
    let r = await updateCall("/api/update/apply");
    if (r.status === 409 && r.data.error === "JOBS_RUNNING") {
      if (!window.confirm(tr("updateJobs", { count: r.data.active_jobs }))) return;
      r = await updateCall("/api/update/apply", { force: true });
    }
    if (r.ok) setApplying(true); else setProblem(r.data.error || "UPDATE_FAILED");
  };
  const acknowledge = async () => { await updateCall("/api/update/ack"); onChange(); };
  return { applying, problem, download, apply, acknowledge };
}

/** Shown on every page when there is something to say about updates: a newer release, its download, or how the last update ended. */
export default function UpdateBanner() {
  const { tr, language } = useLanguage();
  const { state, read } = useUpdate();
  const actions = useUpdateActions(() => void read());
  if (!state) return null;
  const { offer, download, last_result: last } = state;
  const notes = offer ? (offer.notes[language] || offer.notes.vi || offer.notes.en || "") : "";
  const percent = download.total ? Math.min(100, Math.floor((download.done / download.total) * 100)) : 0;
  const box = { margin: "8px 16px", padding: "10px 14px", border: "1px solid var(--border, #bbb)", borderRadius: 8 };
  if (actions.applying) return <div className="notice-bar" role="status" style={box}><strong>{tr("updateApplying")}</strong></div>;
  if (last) {
    return <div className={last.ok ? "notice-bar" : "alert"} role="status" style={box}>
      <strong>{tr(last.ok ? "updateDone" : "updateRolledBack", { version: last.version, from: last.from })}</strong>
      {!last.ok && last.error && <small> · {last.error}</small>}{" "}
      <button type="button" className="action-button" onClick={() => void actions.acknowledge()}>{tr("updateOk")}</button>
    </div>;
  }
  if (!offer) return null;
  const canInstall = state.installed.can_update;
  return <div className={offer.required ? "alert" : "notice-bar"} role="status" style={box}>
    <strong>{tr(offer.required ? "updateRequired" : "updateAvailable", { version: offer.version })}</strong>
    {notes && <small> · {notes}</small>}
    {download.state === "downloading" && <span>
      {" "}{tr("updateDownloading")}
      <progress value={download.done} max={download.total || 1} aria-label={tr("updateDownloading")} style={{ display: "block", width: "100%", height: 14, marginTop: 6 }} />
      <strong>{percent}% · {megabytes(download.done)} / {megabytes(download.total)}</strong>
    </span>}
    {download.state === "ready" && <span>{" "}{tr("updateReady")}{" "}
      <button type="button" className="action-button" onClick={() => void actions.apply()}>{tr("updateApply")}</button></span>}
    {(download.state === "idle" || download.state === "failed") && <span>
      {" "}<small>{tr(offer.kind === "app" ? "updateKindApp" : "updateKindInstaller", { size: megabytes(offer.size) })}</small>
      {offer.failed_before && <small> · {tr("updateFailedBefore")}</small>}
      {download.state === "failed" && <small role="alert"> · {tr("updateFailed")}: {download.error}</small>}{" "}
      {canInstall ? <button type="button" className="action-button" onClick={() => void actions.download()}>{tr(download.state === "failed" ? "updateRetry" : "updateDownload")}</button>
                  : <small>{tr("updateNotInstalled")}</small>}
    </span>}
    {actions.problem && <small role="alert"> · {tr(actions.problem)}</small>}
  </div>;
}
