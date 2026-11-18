"use client";
import { useLanguage } from "@/lib/i18n/language-context";

/** Studio: the person translates by hand. The workflow stops once the Chinese text exists and waits for the translation (loaded on the Reprocess page). */
export default function ManualTranslationToggle({ value, onChange, disabled }: { value: boolean; onChange: (next: boolean) => void; disabled?: boolean }) {
  const { tr } = useLanguage();
  return <label className="auto-tts-toggle manual-toggle">
    <input type="checkbox" checked={value} disabled={disabled} onChange={event => onChange(event.target.checked)} />
    <span>{tr("manualLabel")}</span>
    <small>{tr("manualHelp")}</small>
  </label>;
}
