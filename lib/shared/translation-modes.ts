// Normal: local Hy-MT2 model. Genius: Gemini through the billing gateway (worker/translation/genius.py).
export const translationModes = ["normal", "genius"] as const;
export type TranslationMode = typeof translationModes[number];
export const isTranslationMode = (value: unknown): value is TranslationMode => translationModes.includes(value as TranslationMode);
