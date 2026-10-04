"use client";

import { useEffect, useState } from "react";
import SiteHeader from "@/components/layout/site-header";
import { useNotice } from "@/components/common/use-notice";
import { useLanguage } from "@/lib/i18n/language-context";
import { useTheme } from "@/lib/theme/theme-context";
import ComputeSettings from "@/components/settings/compute-settings";

type Connection = {
  enabled: boolean;
  state: string;
  last_checked: string | null;
  browser_available: boolean;
  legacy_cookie_override: boolean;
  profile_path: string;
};

export default function Settings() {
  const { language, setLanguage, t, tr } = useLanguage();
  const { theme, setTheme } = useTheme();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useNotice();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let mounted = true;
    fetch("/api/settings/youtube", { cache: "no-store" })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        return data as Connection;
      })
      .then((data) => {
        if (mounted) setConnection(data);
      })
      .catch((error) => {
        if (!mounted) return;
        setFailed(true);
        setMessage(error instanceof Error ? error.message : t.settings.loadError);
      });
    return () => {
      mounted = false;
    };
  }, [setMessage, t.settings.loadError]);

  async function act(action: "open" | "check" | "disconnect") {
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      const response = await fetch("/api/settings/youtube", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = await response.json();
      if (typeof data.enabled === "boolean") setConnection(data);
      if (!response.ok) throw new Error(data.error);
      setMessage(
        action === "open"
          ? t.settings.openNotice
          : action === "check"
          ? t.settings.checkNotice
          : t.settings.disconnectNotice
      );
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : t.settings.updateError);
    } finally {
      setBusy(false);
    }
  }

  const connectionStateLabel = (state: string) => {
    return t.settings.ytStatusLabels[state] || t.settings.ytStatusLabels.NOT_CONNECTED;
  };

  return (
    <main className="studio">
      <SiteHeader />
      <section className="hero">
        <span className="eyebrow">{t.settings.eyebrow}</span>
        <h1>{t.settings.title}</h1>
        <p>{t.settings.description}</p>

        {/* Section 1: Ngôn ngữ giao diện (Interface Language) */}
        <section className="lang-switcher-card" aria-label={tr("Language selection")}>
          <h2>{t.settings.langSection}</h2>
          <p>{t.settings.langDesc}</p>
          <div className="lang-options">
            <button
              type="button"
              className={`lang-btn ${language === "vi" ? "active" : ""}`}
              onClick={() => setLanguage("vi")}
              aria-pressed={language === "vi"}
            >
              <strong>
                Tiếng Việt {language === "vi" && <span>✓</span>}
              </strong>
              <small>{t.settings.langVi}</small>
            </button>

            <button
              type="button"
              className={`lang-btn ${language === "en" ? "active" : ""}`}
              onClick={() => setLanguage("en")}
              aria-pressed={language === "en"}
            >
              <strong>
                English {language === "en" && <span>✓</span>}
              </strong>
              <small>{t.settings.langEn}</small>
            </button>
          </div>
        </section>

        <section className="lang-switcher-card" aria-label={tr("Theme selection")}>
          <h2>{tr("Appearance")}</h2>
          <p>{tr("Choose Light or Dark. Your preference is saved on this browser.")}</p>
          <div className="lang-options">
            {(["light", "dark"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`lang-btn ${theme === mode ? "active" : ""}`}
                onClick={() => setTheme(mode)}
                aria-pressed={theme === mode}
              >
                <strong>
                  {tr(mode === "light" ? "Light" : "Dark")}
                  <span aria-hidden="true">{theme === mode ? "✓" : mode === "light" ? "☀" : "☾"}</span>
                </strong>
                <small>{tr(mode === "light" ? "Original light colors" : "Deep navy with blue accents")}</small>
              </button>
            ))}
          </div>
        </section>

        <ComputeSettings />

        {/* YouTube connection remains independent of appearance preferences. */}
        <section className="youtube-connection" aria-label={tr("YouTube connection")}>
          <h2>{t.settings.ytSection}</h2>
          <p>{t.settings.ytDesc}</p>
          <p className="connection-state" role="status">
            {connection ? connectionStateLabel(connection.state) : t.settings.processing}
          </p>
          {connection && (
            <>
              {!connection.browser_available && <p>{t.settings.browserRequired}</p>}
              {connection.legacy_cookie_override && (
                <p>{t.settings.legacyCookieNotice}</p>
              )}
              <ol>
                <li>{t.settings.ytStep1}</li>
                <li>{t.settings.ytStep2}</li>
                <li>{t.settings.ytStep3}</li>
                <li>{t.settings.ytStep4}</li>
              </ol>
              {connection.state === "CLOSE_LOGIN_WINDOW" && (
                <p role="status">{t.settings.closeWindowNotice}</p>
              )}
              <div className="youtube-actions">
                <button
                  className="action-button"
                  disabled={busy || !connection.browser_available}
                  onClick={() => void act("open")}
                >
                  {connection.enabled ? t.settings.reconnect : t.settings.connect}
                </button>
                <button
                  className="action-button"
                  disabled={busy || !connection.enabled}
                  onClick={() => void act("check")}
                >
                  {t.settings.check}
                </button>
                <button
                  className="text-button"
                  disabled={busy || !connection.enabled}
                  onClick={() => void act("disconnect")}
                >
                  {t.settings.disconnect}
                </button>
              </div>
              {connection.last_checked && (
                <p>
                  {t.settings.lastChecked}{" "}
                  {new Date(connection.last_checked).toLocaleString(
                    language === "vi" ? "vi-VN" : "en-US"
                  )}
                </p>
              )}
              <details>
                <summary>{t.settings.profileLocation}</summary>
                <code>{connection.profile_path}</code>
              </details>
            </>
          )}
          {busy && <p role="status">{t.settings.processing}</p>}
          {message && (
            <p
              className={failed ? "alert" : "connection-message"}
              role={failed ? "alert" : "status"}
            >
              {message}
            </p>
          )}
        </section>

        <p>{t.settings.ytSecurityNote1}</p>
        <p>{t.settings.ytSecurityNote2}</p>
      </section>
    </main>
  );
}
