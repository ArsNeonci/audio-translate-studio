"use client";
import { apiFetch } from "@audio/ui";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";

type Memory = { start_free_gib: number; default_gib: number; min_gib: number; max_gib: number; step_gib: number; customised: boolean; available_gib: number; total_gib: number };

/** The free RAM a translation waits for before it starts. Moving the slider saves it and applies to workflows that are already waiting. */
export default function TranslationMemorySettings() {
  const { tr } = useLanguage();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [value, setValue] = useState<number | null>(null);   // what the slider shows while it is being moved
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    const response = await apiFetch("/api/settings/translation-memory", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    setMemory(data);
    return data as Memory;
  }, []);

  useEffect(() => {
    let live = true;
    const tick = () => load().then((data) => { if (live) setValue((current) => current ?? data.start_free_gib); }).catch(() => { if (live) { setFailed(true); setMessage("memoryUnavailable"); } });
    tick();
    const interval = setInterval(() => { load().catch(() => undefined); }, 5000);   // the free RAM moves; the slider's own value is not touched
    return () => { live = false; clearInterval(interval); if (timer.current) clearTimeout(timer.current); };
  }, [load]);

  async function save(next: number) {
    setFailed(false); setMessage("");
    try {
      const response = await apiFetch("/api/settings/translation-memory", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ start_free_gib: next }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      setMemory(data); setMessage("memorySaved");
    } catch { setFailed(true); setMessage("memoryUnavailable"); }
  }

  function change(next: number) {
    setValue(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void save(next), 400);   // one save when the slider rests, not one per step
  }

  const shown = value ?? memory?.start_free_gib ?? null;
  const enough = memory && shown !== null ? memory.available_gib >= shown : null;
  return (
    <section className="lang-switcher-card" aria-label={tr("memoryTitle")}>
      <h2>{tr("memoryTitle")}</h2>
      <p>{tr("memoryDescription")}</p>
      {memory && shown !== null ? (
        <>
          <div className="memory-slider">
            <input type="range" min={memory.min_gib} max={memory.max_gib} step={memory.step_gib} value={shown}
              aria-label={tr("memoryTitle")} aria-valuetext={tr("memoryValue", { value: shown })} onChange={(event) => change(Number(event.target.value))} />
            <strong>{tr("memoryValue", { value: shown })}</strong>
          </div>
          <div className="memory-scale" aria-hidden="true"><span>{tr("memoryValue", { value: memory.min_gib })}</span><span>{tr("memoryValue", { value: memory.max_gib })}</span></div>
          <p role="status">{tr("memoryNow", { available: memory.available_gib, total: memory.total_gib })} · {tr(enough ? "memoryEnough" : "memoryWaiting")}</p>
          {shown < memory.default_gib && <p>{tr("memoryLow", { value: memory.default_gib })}</p>}
          {shown !== memory.default_gib && (
            <button type="button" className="action-button" onClick={() => change(memory.default_gib)}>{tr("memoryReset", { value: memory.default_gib })}</button>
          )}
        </>
      ) : null}
      {message && <p role={failed ? "alert" : "status"}>{tr(message)}</p>}
    </section>
  );
}
