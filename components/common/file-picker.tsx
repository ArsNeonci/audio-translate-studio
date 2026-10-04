"use client";

import { useLanguage } from "@/lib/i18n/language-context";

export default function FilePicker({ accept, file, onChange }: { accept: string; file: File | null; onChange: (file: File | null) => void }) {
  const { t } = useLanguage();
  return <label className="file-picker">
    <span>{t.tools.chooseFile}</span>
    <span className="file-picker-name">{file?.name || t.tools.noFileChosen}</span>
    <input type="file" aria-label={t.tools.inputFile} required accept={accept} onChange={event => onChange(event.target.files?.[0] || null)} />
  </label>;
}
