"use client";
import { useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";

// An audio element that says so when the file cannot be played, instead of showing a dead 0:00 / 0:00 player.
export default function AudioPlayer({ src, label }: { src: string; label: string }) {
  const { tr } = useLanguage();
  const [failed, setFailed] = useState(false);
  if (failed) return <p className="audio-error" role="alert">{tr("Không phát được audio này trong trình duyệt. Hãy dùng nút tải xuống.")}</p>;
  return <audio className="audio-player" controls preload="metadata" src={src} aria-label={label} onError={() => setFailed(true)} />;
}
