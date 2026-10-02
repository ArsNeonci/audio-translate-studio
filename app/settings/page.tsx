"use client";

import { useEffect, useState } from "react";
import SiteHeader from "@/app/components/site-header";
import { useNotice } from "@/app/components/use-notice";
import { useLanguage } from "@/lib/language-context";

type Connection = {
  enabled: boolean;
  state: string;
  last_checked: string | null;
  browser_available: boolean;
  legacy_cookie_override: boolean;
  profile_path: string;
};

export default function Settings() {
  const { language, setLanguage, t } = useLanguage();
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
        setMessage(error instanceof Error ? error.message : t.settings.failedLoad);
      });
    return () => {
      mounted = false;
    };
  }, [setMessage, t.settings.failedLoad]);

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
          ? t.settings.msgOpen
          : action === "check"
          ? t.settings.msgCheck
          : t.settings.msgDisconnect
      );
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : t.settings.msgFailed);
    } finally {
      setBusy(false);
    }
  }

  const connectionStateLabel = (state: string) => {
    const states: Record<string, string> = {
      NOT_CONNECTED: t.settings.stateNotConnected,
      AWAITING_SIGN_IN: t.settings.stateAwaitingSignIn,
      CLOSE_LOGIN_WINDOW: t.settings.stateCloseLoginWindow,
      SESSION_SAVED: t.settings.stateSessionSaved,
      SIGN_IN_REQUIRED: t.settings.stateSignInRequired,
    };
    return states[state] || t.settings.stateNotConnected;
  };

  return (
    <main className="studio">
      <SiteHeader />
      <section className="hero">
        <span className="eyebrow">{t.settings.eyebrow}</span>
        <h1>{t.settings.title}</h1>
        <p>{t.settings.description}</p>

        {/* Section 1: Ngôn ngữ giao diện (Interface Language) */}
        <section className="lang-switcher-card" aria-label="Language selection">
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

        {/* Section 2: Kết nối YouTube */}
        <section className="youtube-connection" aria-label="YouTube connection">
          <h2>
            {connection ? connectionStateLabel(connection.state) : t.settings.loading}
          </h2>
          {connection && (
            <>
              {!connection.browser_available && <p>{t.settings.browserReq}</p>}
              {connection.legacy_cookie_override && (
                <p>{t.settings.cookieOverrideNote}</p>
              )}
              <ol>
                <li>{t.settings.step1}</li>
                <li>{t.settings.step2}</li>
                <li>{t.settings.step3}</li>
                <li>{t.settings.step4}</li>
              </ol>
              {connection.state === "CLOSE_LOGIN_WINDOW" && (
                <p role="status">{t.settings.stateCloseLoginWindow}</p>
              )}
              <div className="youtube-actions">
                <button
                  className="action-button"
                  disabled={busy || !connection.browser_available}
                  onClick={() => void act("open")}
                >
                  {connection.enabled ? t.settings.btnReLogin : t.settings.btnConnect}
                </button>
                <button
                  className="action-button"
                  disabled={busy || !connection.enabled}
                  onClick={() => void act("check")}
                >
                  {t.settings.btnCheck}
                </button>
                <button
                  className="text-button"
                  disabled={busy || !connection.enabled}
                  onClick={() => void act("disconnect")}
                >
                  {t.settings.btnDisconnect}
                </button>
              </div>
              {connection.last_checked && (
                <p>
                  {t.settings.lastChecked}:{" "}
                  {new Date(connection.last_checked).toLocaleString(
                    language === "vi" ? "vi-VN" : "en-US"
                  )}
                </p>
              )}
              <details>
                <summary>{t.settings.storageLocation}</summary>
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

        <p>{t.settings.securityNote1}</p>
        <p>{t.settings.securityNote2}</p>
      </section>
    </main>
  );
}
