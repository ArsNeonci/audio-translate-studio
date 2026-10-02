"use client";

import React, { createContext, useContext, useEffect, useMemo, useSyncExternalStore } from "react";
import { translations, type Language, type Translations } from "./i18n";

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: Translations;
  isReady: boolean;
}

const STORAGE_KEY = "audio-studio-lang";

const defaultContext: LanguageContextType = {
  language: "vi",
  setLanguage: () => {},
  t: translations.vi,
  isReady: false,
};

const LanguageContext = createContext<LanguageContextType>(defaultContext);

function getLanguageSnapshot(): Language {
  if (typeof window === "undefined") return "vi";
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "en" || stored === "vi" ? stored : "vi";
  } catch {
    return "vi";
  }
}

function getServerSnapshot(): Language {
  return "vi";
}

function subscribe(callback: () => void) {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", callback);
  window.addEventListener("audio-studio-lang-change", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("audio-studio-lang-change", callback);
  };
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const language = useSyncExternalStore(subscribe, getLanguageSnapshot, getServerSnapshot);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = (lang: Language) => {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
      document.documentElement.lang = lang;
      window.dispatchEvent(new Event("audio-studio-lang-change"));
    } catch {
      // Ignore
    }
  };

  const t = useMemo(() => translations[language] || translations.vi, [language]);

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      t,
      isReady: true,
    }),
    [language, t]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  return useContext(LanguageContext);
}
