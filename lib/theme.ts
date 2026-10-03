export type Theme = "light" | "dark";
export const THEME_STORAGE_KEY = "audio-studio-theme";

export function normalizeTheme(value: string | null): Theme {
  return value === "dark" ? "dark" : "light";
}

// Runs before the page paints; the saved theme does not flash Light on reload.
export const themeBootstrap = `(function(){var t='light';try{t=localStorage.getItem('${THEME_STORAGE_KEY}')==='dark'?'dark':'light'}catch(e){}document.documentElement.dataset.theme=t;document.documentElement.style.colorScheme=t})()`;
