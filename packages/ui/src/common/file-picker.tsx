"use client";

// A file field styled as a button with the chosen name beside it. The texts come from the caller (each app has its own wording).
export default function FilePicker({ accept, file, onChange, chooseLabel, emptyLabel, inputLabel }: {
  accept: string; file: File | null; onChange: (file: File | null) => void; chooseLabel: string; emptyLabel: string; inputLabel: string;
}) {
  return <label className="file-picker">
    <span className="file-picker-button">{chooseLabel}</span>
    <span className="file-picker-name">{file?.name || emptyLabel}</span>
    <input type="file" aria-label={inputLabel} required accept={accept} onChange={event => onChange(event.target.files?.[0] || null)} />
  </label>;
}
