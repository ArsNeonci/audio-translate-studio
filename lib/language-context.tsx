"use client";

import React, { createContext, useContext, useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { translations, type Language, type Translations } from "./i18n";
import { translateUi } from './ui-text';

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: Translations;
  isReady: boolean;
  tr: (text: string, values?: Record<string, string | number>) => string;
}

const STORAGE_KEY = "audio-studio-lang";
let memoryLanguage: Language = 'vi';

const defaultContext: LanguageContextType = {
  language: "vi",
  setLanguage: () => {},
  t: translations.vi,
  isReady: false,
  tr: (text, values) => translateUi(text, 'vi', values),
};

const LanguageContext = createContext<LanguageContextType>(defaultContext);

function getLanguageSnapshot(): Language {
  if (typeof window === "undefined") return "vi";
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    memoryLanguage = stored === "en" || stored === "vi" ? stored : memoryLanguage;
    return memoryLanguage;
  } catch {
    return memoryLanguage;
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
  const tr = useCallback((text: string, values?: Record<string, string | number>) => translateUi(text, language, values), [language]);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = useCallback((lang: Language) => {
    memoryLanguage = lang;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // Keep the switch functional when browser storage is unavailable.
    }
    window.dispatchEvent(new Event("audio-studio-lang-change"));
  }, []);

  const t = useMemo(() => translations[language] || translations.vi, [language]);

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      t,
      isReady: true,
      tr,
    }),
    [language, t, tr, setLanguage]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  return useContext(LanguageContext);
}
