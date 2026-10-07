"use client";

import { useEffect, useRef, useState } from "react";
import SiteHeader from "@/components/layout/site-header";
import type { LicenseStatus } from "@/components/license/license-status";
import { useNotice } from "@/components/common/use-notice";
import { useLanguage } from "@/lib/i18n/language-context";
import { openBillingPage } from "@/lib/shared/billing-client";

export default function LicensePage() {
  const { language, t, tr } = useLanguage();
  const [status, setStatus] = useState<LicenseStatus>({ status: "CHECKING" });
  const [machine, setMachine] = useState("");
  const [token, setToken] = useState("");
  const [action, setAction] = useState("activate");
  const [message, setMessage] = useNotice();
  const [busy, setBusy] = useState(false);
  const [billing, setBilling] = useState<{ code?: string; portal_url?: string; enabled: boolean } | null>(null);
  const [watchUntil, setWatchUntil] = useState(0);
  const sequence = useRef(0);
  useEffect(() => { sequence.current = status.sequence ?? 0; }, [status.sequence]);

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
        if (!disposed) setMessage(t.license.cannotRead);
      });
    return () => {
      disposed = true;
    };
  }, [setMessage, t.license.cannotRead]);

  // The Customer Code is remembered while the licence is valid, so it is read again once the licence is known to be active.
  useEffect(() => {
    let disposed = false;
    void fetch("/api/billing", { cache: "no-store" }).then((r) => r.json()).then((b) => { if (!disposed) setBilling(b); }).catch(() => undefined);
    return () => { disposed = true; };
  }, [status.status]);

  // After the portal is opened, look for the paid renewal every few seconds (the server installs it) for 15 minutes.
  useEffect(() => {
    if (!watchUntil) return;
    const timer = setInterval(() => {
      if (Date.now() > watchUntil) { setWatchUntil(0); return; }
      void fetch("/api/license", { cache: "no-store" }).then((r) => r.json()).then((s: LicenseStatus) => {
        setStatus(s);
        if ((s.sequence ?? 0) > sequence.current) { setMessage(tr("billingRenewed")); setWatchUntil(0); }
      }).catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, [watchUntil, setMessage, tr]);

  async function openPortal(destination: "license" | "debt") {
    setMessage("");
    const result = await openBillingPage(destination);
    if (!result.ok) { setMessage(tr(result.error === "BILLING_CODE_UNKNOWN" ? result.error : "billingUnavailable")); return; }
    setMessage(tr(result.mode === "home" ? "billingOpenedHome" : result.mode === "code" ? "billingOpenedCode" : "billingOpened"));
    if (destination === "license") setWatchUntil(Date.now() + 15 * 60 * 1000);
  }

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
      setMessage(t.license.savedNotice);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t.license.saveFailed);
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
          <strong>{tr(status.status)}</strong>
          {status.sequence ? ` · ${tr("Sequence")} ${status.sequence}` : ""}
          {status.expires_at
            ? ` · ${t.license.expires}: ${new Date(status.expires_at).toLocaleString(
                language === "vi" ? "vi-VN" : "en-US"
              )}`
            : ""}
        </p>

        {billing?.enabled && (
          <div className="license-box">
            <h2>{tr("billingTitle")}</h2>
            <p>{tr("billingIntro")}</p>
            {billing.code && (
              <>
                <label htmlFor="customer-code">{tr("billingCode")}</label>
                <div className="machine-row">
                  <input id="customer-code" readOnly value={billing.code} />
                  <button
                    type="button"
                    className="action-button"
                    onClick={() => void navigator.clipboard.writeText(billing.code ?? "").then(() => setMessage(t.license.copied)).catch(() => setMessage(t.license.copyPrompt))}
                  >
                    {t.license.copy}
                  </button>
                </div>
                <p><small>{tr("billingCodeHelp")}</small></p>
              </>
            )}
            <div className="license-actions">
              <button type="button" className="action-button" onClick={() => void openPortal("license")}>{tr("billingBuy")}</button>{" "}
              <button type="button" className="action-button" onClick={() => void openPortal("debt")}>{tr("billingDebt")}</button>
            </div>
          </div>
        )}

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
                  .then(() => setMessage(t.license.copied))
                  .catch(() => setMessage(t.license.copyPrompt))
              }
            >
              {t.license.copy}
            </button>
          </div>

          <p>{t.license.instructions}</p>

          <form onSubmit={submit}>
            <label htmlFor="license-action">{t.license.tokenType}</label>
            <select
              id="license-action"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            >
              <option value="activate">{t.license.activateFirst}</option>
              <option value="renew">{t.license.renew}</option>
            </select>

            <label htmlFor="license-token">{t.license.tokenLabel}</label>
            <textarea
              id="license-token"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              rows={6}
              maxLength={34000}
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
