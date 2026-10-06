"use client";

import { useEffect, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import { useLicense } from "@/components/license/license-status";

type Compute = {
  device: "cpu" | "gpu";
  capabilities: { transcription: boolean; translation: boolean; tts: boolean; gpu_name: string | null };
};

export default function ComputeSettings() {
  const { tr } = useLanguage();
  const [config, setConfig] = useState<Compute | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let mounted = true;
    fetch("/api/settings/compute", { cache: "no-store" }).then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      if (mounted) setConfig(data);
    }).catch(() => { if (mounted) { setFailed(true); setMessage("Compute settings unavailable"); } });
    return () => { mounted = false; };
  }, []);

  async function select(device: Compute["device"]) {
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      const response = await fetch("/api/settings/compute", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      setConfig(data);
      setMessage("computeSaved");
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Compute settings unavailable");
    } finally { setBusy(false); }
  }

  const license = useLicense();
  const basic = license.edition === "basic";
  // Basic generates the voice on the server, so local TTS GPU support is not required there.
  const ready = config && config.capabilities.transcription && config.capabilities.translation && (basic || config.capabilities.tts);
  return (
    <section className="lang-switcher-card" aria-label={tr("computeTitle")}>
      <h2>{tr("computeTitle")}</h2>
      <p>{tr("computeDescription")}</p>
      <div className="lang-options">
        {(["cpu", "gpu"] as const).map((device) => (
          <button key={device} type="button" disabled={!config || busy}
            className={`lang-btn ${config?.device === device ? "active" : ""}`}
            aria-pressed={config?.device === device} onClick={() => select(device)}>
            <strong>{device.toUpperCase()}<span aria-hidden="true">{config?.device === device ? "✓" : ""}</span></strong>
            <small>{tr(device === "cpu" ? "computeCPU" : "computeGPU")}</small>
          </button>
        ))}
      </div>
      <p>{tr("computeMergeNote")}</p>
      {basic && <p>{tr("ttsComputeBasic")}</p>}
      {config && <p role="status">{tr(ready ? "computeGPUReady" : "computeGPUUnavailable")}{config.capabilities.gpu_name ? ` (${config.capabilities.gpu_name})` : ""}</p>}
      {message && <p role={failed ? "alert" : "status"}>{tr(message)}</p>}
    </section>
  );
}
