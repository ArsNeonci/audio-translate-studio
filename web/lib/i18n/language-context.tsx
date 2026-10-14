"use client";

import { createLanguageProvider, useLanguage as useSharedLanguage } from "@audio/ui";
import { translations, type Translations } from "@/lib/i18n/i18n";
import { translateUi } from "@/lib/i18n/ui-text";

// The mechanism (choice kept in the browser, shared between tabs) is in @audio/ui; the texts are this app's.
export const LanguageProvider = createLanguageProvider({ translations, translateUi, storageKey: "audio-studio-lang" });
export const useLanguage = () => useSharedLanguage<Translations>();
