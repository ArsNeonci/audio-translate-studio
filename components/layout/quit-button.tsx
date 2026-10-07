"use client";

import { useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";

type Reply = { installed: boolean; active_jobs: number; stopped: boolean };

// Closing the tab leaves the app running in the background. This stops it completely (web server and every worker).
export default function QuitButton() {
  const { tr } = useLanguage();
  const [state, setState] = useState<"idle" | "asking" | "stopped" | "unavailable">("idle");
  const send = async (force: boolean) => {
    setState("asking");
    try {
      const reply = (await (await fetch("/api/quit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force }) })).json()) as Reply;
      if (!reply.installed) { setState("unavailable"); return; }
      if (reply.stopped) { setState("stopped"); return; }
      // Workflows are running: ask once, in the browser's own dialog, before stopping them.
      if (window.confirm(tr("quitConfirm", { count: reply.active_jobs }))) await send(true); else setState("idle");
    } catch { setState("idle"); }
  };
  if (state === "stopped") return <div role="status" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.72)", color: "#fff", display: "grid", placeItems: "center", textAlign: "center", zIndex: 9999, padding: 24 }}><p><strong>{tr("quitDone")}</strong><br />{tr("quitDoneHint")}</p></div>;
  return (
    <button type="button" className="action-button" disabled={state === "asking"} title={tr("quitHint")} onClick={() => void send(false)}>
      {tr(state === "unavailable" ? "quitUnavailable" : "quitLabel")}
    </button>
  );
}
