"use client";
import { useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import { updateCall, useUpdate } from "@/components/layout/update-banner";

/** Settings: the installed version, when the gateway was last asked, and a button to ask now. Installing is done from the banner. */
export default function UpdateSettings() {
  const { tr, language } = useLanguage();
  const { state, setState, read } = useUpdate();
  const [busy, setBusy] = useState(false);
  async function check() {
    setBusy(true);
    try { const r = await updateCall("/api/update/check"); if (r.ok) setState(r.data); else await read(); } finally { setBusy(false); }
  }
  const when = state?.checked_at ? new Date(state.checked_at * 1000).toLocaleString(language === "vi" ? "vi-VN" : "en-US") : tr("updateNever");
  return <section className="lang-switcher-card" aria-label={tr("updateTitle")}>
    <h2>{tr("updateTitle")}</h2>
    <p>{tr("updateDescription")}</p>
    {state && <>
      <p role="status"><strong>{tr("updateCurrent", { version: state.installed.version || "—" })}</strong> · {tr("updateChannel", { channel: state.channel })} · {tr("updateLastChecked", { when })}</p>
      <p role="status">{state.offer ? tr(state.offer.required ? "updateRequired" : "updateAvailable", { version: state.offer.version }) : tr(state.error ? "updateCheckError" : "updateUpToDate")}{state.error && !state.offer && <small> · {state.error}</small>}</p>
      <button type="button" className="action-button" disabled={busy} onClick={() => void check()}>{tr(busy ? "updateChecking" : "updateCheck")}</button>
    </>}
  </section>;
}
