"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { normalizeTheme, THEME_STORAGE_KEY, type Theme } from "./theme";

const CHANGE_EVENT = "audio-studio-theme-change";
let memoryTheme: Theme = "light";
let storageAvailable = true;
const ThemeContext = createContext<{ theme: Theme; setTheme: (theme: Theme) => void }>({
  theme: "light",
  setTheme: () => {},
});

function getSnapshot(): Theme {
  if (!storageAvailable) return memoryTheme;
  try {
    memoryTheme = normalizeTheme(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    // The switch also works for this session when storage is unavailable.
  }
  return memoryTheme;
}

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(CHANGE_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(CHANGE_EVENT, callback);
  };
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribe, getSnapshot, () => "light" as Theme);
  // Hydration initially uses the Light server snapshot; keep the prepaint
  // selection until useSyncExternalStore has read the browser preference.
  useEffect(() => applyTheme(getSnapshot()), [theme]);

  const setTheme = useCallback((nextTheme: Theme) => {
    memoryTheme = nextTheme;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch {
      // Persist in memory if browser storage is blocked.
      storageAvailable = false;
    }
    applyTheme(nextTheme);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
