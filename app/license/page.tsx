"use client";

import { useEffect, useState } from "react";
import SiteHeader from "../components/site-header";
import type { LicenseStatus } from "../components/license-status";
import { useNotice } from "../components/use-notice";
import { useLanguage } from "@/lib/language-context";

export default function LicensePage() {
  const { language, t } = useLanguage();
  const [status, setStatus] = useState<LicenseStatus>({ status: "CHECKING" });
  const [machine, setMachine] = useState("");
  const [token, setToken] = useState("");
  const [action, setAction] = useState("activate");
  const [message, setMessage] = useNotice();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let disposed = false;
    void Promise.all([
      fetch("/api/license", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/license?machine=1", { cache: "no-store" }).then((r) => r.json()),
    ])
      .then(([s, m]) => {
        if (!disposed) {
          setStatus(s);
          setMachine(m.machine_id || "");
          if (m.error) setMessage(m.error);
        }
      })
      .catch(() => {
        if (!disposed) setMessage(t.license.failedLoad);
      });
    return () => {
      disposed = true;
    };
  }, [setMessage, t.license.failedLoad]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/license", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, token: token.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || data.status);
      setStatus(data);
      setToken("");
      setMessage(t.license.savedSuccess);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t.license.failedImport);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="studio">
      <SiteHeader />
      <section className="hero">
        <div className="eyebrow">{t.license.eyebrow}</div>
        <h1>{t.license.title}</h1>
        <p role="status">
          <strong>{status.status}</strong>
          {status.sequence ? ` · Sequence ${status.sequence}` : ""}
          {status.expires_at
            ? ` · ${t.license.expires}: ${new Date(status.expires_at).toLocaleString(
                language === "vi" ? "vi-VN" : "en-US"
              )}`
            : ""}
        </p>

        <div className="license-box">
          <label htmlFor="machine-id">{t.license.machineId}</label>
          <div className="machine-row">
            <input id="machine-id" readOnly value={machine} />
            <button
              type="button"
              className="action-button"
              disabled={!machine}
              onClick={() =>
                void navigator.clipboard
                  .writeText(machine)
                  .then(() => setMessage(t.license.copiedMachineId))
                  .catch(() => setMessage(t.license.copyFallback))
              }
            >
              {t.license.copyBtn}
            </button>
          </div>

          <p>{t.license.adminInstruction}</p>

          <form onSubmit={submit}>
            <label htmlFor="license-action">{t.license.tokenType}</label>
            <select
              id="license-action"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            >
              <option value="activate">{t.license.activateFirst}</option>
              <option value="renew">{t.license.renewOption}</option>
            </select>

            <label htmlFor="license-token">{t.license.tokenInputLabel}</label>
            <textarea
              id="license-token"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              rows={6}
              maxLength={34000}
              placeholder={t.license.tokenPlaceholder}
            />

            <div className="license-actions">
              <button
                type="submit"
                className="action-button"
                disabled={busy || !token.trim()}
              >
                {busy ? t.license.verifying : t.license.verifyAndSave}
              </button>
            </div>
          </form>
        </div>

        {message && (
          <p className="alert" role="status" style={{ marginTop: "16px" }}>
            {message}
          </p>
        )}
      </section>
    </main>
  );
}
