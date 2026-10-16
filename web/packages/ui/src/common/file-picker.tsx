"use client";
import { useState } from "react";

// A file field styled as a button with the chosen name beside it. The texts come from the caller (each app has its own wording).
// The type (and size) are checked when the file is chosen: a file that does not fit is refused at once with `rejectLabel` / `tooBigLabel`,
// instead of being taken in and failing only when the work starts. `accept` is a list such as ".txt,.md".
export default function FilePicker({ accept, file, onChange, chooseLabel, emptyLabel, inputLabel, rejectLabel, maxBytes, tooBigLabel }: {
  accept: string; file: File | null; onChange: (file: File | null) => void; chooseLabel: string; emptyLabel: string; inputLabel: string;
  rejectLabel?: string; maxBytes?: number; tooBigLabel?: string;
}) {
  const [problem, setProblem] = useState("");
  function choose(event: React.ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0] || null;
    const allowed = accept.split(",").map(item => item.trim().toLowerCase()).filter(Boolean);
    const extension = picked && picked.name.includes(".") ? picked.name.slice(picked.name.lastIndexOf(".")).toLowerCase() : "";
    const bad = picked && allowed.length > 0 && !allowed.includes(extension) ? rejectLabel || "" : picked && maxBytes && picked.size > maxBytes ? tooBigLabel || "" : "";
    if (picked && bad) { event.target.value = ""; setProblem(bad); onChange(null); return; }
    setProblem(""); onChange(picked);
  }
  return <>
    <label className="file-picker">
      <span className="file-picker-button">{chooseLabel}</span>
      <span className="file-picker-name">{file?.name || emptyLabel}</span>
      <input type="file" aria-label={inputLabel} required accept={accept} onChange={choose} />
    </label>
    {problem && <small role="alert" className="video-bad">{problem}</small>}
  </>;
}
