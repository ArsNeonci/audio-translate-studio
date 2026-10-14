// @audio/ui: what the app and the admin share. The API address (apiFetch), the theme, the language mechanism, small common components.
export { apiFetch, apiUrl, setApiBase } from "./api";
export { ThemeProvider, useTheme } from "./theme/theme-context";
export { normalizeTheme, themeBootstrap, THEME_STORAGE_KEY, type Theme } from "./theme/theme";
export { createLanguageProvider, useLanguage, type Language, type LanguageApi, type LanguageConfig } from "./i18n/language";
export { default as AudioPlayer } from "./common/audio-player";
export { default as FilePicker } from "./common/file-picker";
export { useNotice } from "./common/use-notice";
export { EyeIcon, TrashIcon, DownloadIcon, RegenerateIcon } from "./common/action-icons";
