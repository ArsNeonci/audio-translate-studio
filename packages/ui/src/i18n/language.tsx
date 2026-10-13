"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore } from "react";

// What every screen needs from the language: the current one, a way to change it, the typed dictionary of the app (T) and tr(), the
// translator for plain texts. The dictionaries and the translator belong to the app (or to the admin); this file is only the mechanism:
// the choice is kept in the browser, shared between tabs, and survives a browser that refuses storage.
export type Language = "vi" | "en";
export interface LanguageApi<T = unknown> {
  language: Language;
  setLanguage: (language: Language) => void;
  t: T;
  isReady: boolean;
  tr: (text: string, values?: Record<string, string | number>) => string;
}
export interface LanguageConfig<T> {
  translations: Record<Language, T>;
  translateUi: (text: string, language: Language, values?: Record<string, string | number>) => string;
  storageKey: string;
}

const defaults: LanguageApi = { language: "vi", setLanguage: () => {}, t: {}, isReady: false, tr: (text) => text };
const LanguageContext = createContext<LanguageApi>(defaults);

export function createLanguageProvider<T>({ translations, translateUi, storageKey }: LanguageConfig<T>) {
  const changeEvent = `${storageKey}-change`;
  let memoryLanguage: Language = "vi";

  const getSnapshot = (): Language => {
    if (typeof window === "undefined") return "vi";
    try {
      const stored = localStorage.getItem(storageKey);
      memoryLanguage = stored === "en" || stored === "vi" ? stored : memoryLanguage;
    } catch { /* storage unavailable: the choice lives in memory for this session */ }
    return memoryLanguage;
  };
  const getServerSnapshot = (): Language => "vi";
  const subscribe = (callback: () => void) => {
    if (typeof window === "undefined") return () => {};
    window.addEventListener("storage", callback);
    window.addEventListener(changeEvent, callback);
    return () => { window.removeEventListener("storage", callback); window.removeEventListener(changeEvent, callback); };
  };

  return function LanguageProvider({ children }: { children: React.ReactNode }) {
    const language = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
    const tr = useCallback((text: string, values?: Record<string, string | number>) => translateUi(text, language, values), [language]);
    useEffect(() => { document.documentElement.lang = language; }, [language]);
    const setLanguage = useCallback((next: Language) => {
      memoryLanguage = next;
      try { localStorage.setItem(storageKey, next); } catch { /* keep the switch working without storage */ }
      window.dispatchEvent(new Event(changeEvent));
    }, []);
    const t = useMemo(() => translations[language] || translations.vi, [language]);
    const value = useMemo<LanguageApi>(() => ({ language, setLanguage, t, isReady: true, tr }), [language, setLanguage, t, tr]);
    return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
  };
}

export function useLanguage<T = unknown>(): LanguageApi<T> {
  return useContext(LanguageContext) as LanguageApi<T>;
}
