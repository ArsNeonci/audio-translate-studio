"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";

type ModelState = { phase: "ready" | "missing" | "downloading" | "verifying" | "error"; done: number; total: number; error?: string; rate?: number; eta?: number; license?: string };
const gigabytes = (bytes: number) => (bytes / 1024 ** 3).toFixed(2);

// Shown on every page until the offline translation model is on this computer. The model is downloaded after activation, so
// a fresh install has no model and the first Normal-mode translation would otherwise fail with MODEL_MISSING.
export default function ModelBanner() {
  const { tr } = useLanguage();
  const [state, setState] = useState<ModelState | null>(null);
  const [starting, setStarting] = useState(false);
  const read = useCallback(async () => {
    try { setState((await (await fetch("/api/model", { cache: "no-store" })).json()) as ModelState); } catch { /* server restarting */ }
  }, []);
  useEffect(() => {
    const first = setTimeout(() => void read(), 0); // asynchronous, so no state is set while the effect runs
    const timer = setInterval(() => void read(), 1500);
    return () => { clearTimeout(first); clearInterval(timer); };
  }, [read]);
  // The button is locked from the click until the server has answered, and the server runs one download at a time, so a
  // double click (or a second window) can never start a second download.
  const start = async () => {
    if (starting) return;
    setStarting(true);
    try { setState((await (await fetch("/api/model", { method: "POST" })).json()) as ModelState); } catch { /* shown on the next poll */ }
    finally { setStarting(false); }
  };
  if (!state || state.phase === "ready") return null;
  const busy = state.phase === "downloading" || state.phase === "verifying";
  const percent = Math.min(100, Math.floor((state.done / state.total) * 100));
  const needsLicense = !busy && state.license !== undefined && state.license !== "ACTIVE";
  let detail = `${percent}% · ${gigabytes(state.done)} / ${gigabytes(state.total)} GB`;
  if (state.phase === "downloading" && state.rate) detail += ` · ${tr("modelSpeed", { speed: (state.rate / 1024 ** 2).toFixed(1) })}`;
  if (state.phase === "downloading" && state.eta) detail += ` · ${tr("modelEta", { minutes: Math.max(1, Math.ceil(state.eta / 60)) })}`;
  return (
    <div className="notice-bar" role="status" style={{ margin: "8px 16px", padding: "10px 14px", border: "1px solid var(--border, #bbb)", borderRadius: 8 }}>
      <strong>{tr("modelTitle")}</strong>{" "}
      {busy ? (
        <span>
          {tr(state.phase === "verifying" ? "modelVerifying" : "modelDownloading")}
          <progress value={state.done} max={state.total} aria-label={tr("modelTitle")} style={{ display: "block", width: "100%", height: 14, marginTop: 6 }} />
          <strong>{detail}</strong>
        </span>
      ) : needsLicense ? (
        <span>{tr("modelNeedsLicense")} <Link href="/license" className="action-button">{tr("modelOpenLicense")}</Link></span>
      ) : (
        <span>
          {tr(state.phase === "error" ? `modelError.${state.error ?? "MODEL_DOWNLOAD_FAILED"}` : "modelMissing")}{" "}
          <button type="button" className="action-button" disabled={starting} onClick={() => void start()}>{tr(state.phase === "error" ? "modelRetry" : "modelDownload")}</button>
        </span>
      )}
    </div>
  );
}
