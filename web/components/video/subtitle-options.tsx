"use client";
import { useLanguage } from "@/lib/i18n/language-context";

/** The two numbers that shape the subtitle cues (worker/audio_translate/video/subtitles.py): characters per cue and the least time a cue stays up. */
export type SubtitleSettings = { max_chars: number; min_seconds: number };
export const defaultSubtitle = (): SubtitleSettings => ({ max_chars: 84, min_seconds: 1 });
export const subtitleLimits = { max_chars: [20, 200], min_seconds: [0.5, 5] } as const;
export const subtitleValid = (value: SubtitleSettings) =>
  Number.isInteger(value.max_chars) && value.max_chars >= subtitleLimits.max_chars[0] && value.max_chars <= subtitleLimits.max_chars[1]
  && value.min_seconds >= subtitleLimits.min_seconds[0] && value.min_seconds <= subtitleLimits.min_seconds[1];
export const subtitleFromJob = (saved?: Partial<SubtitleSettings> | null): SubtitleSettings => ({ ...defaultSubtitle(), ...(saved || {}) });

/** Cue length and reading time for the .srt (and for subtitles burned into the picture). The defaults suit most videos. */
export default function SubtitleOptions({ value, onChange, disabled }: { value: SubtitleSettings; onChange: (next: SubtitleSettings) => void; disabled?: boolean }) {
  const { tr } = useLanguage();
  const ok = subtitleValid(value);
  return <fieldset className="subtitle-options" disabled={disabled}>
    <legend>{tr("subtitleTitle")}</legend>
    <label>{tr("subtitleMaxChars")}
      <input type="number" inputMode="numeric" min={subtitleLimits.max_chars[0]} max={subtitleLimits.max_chars[1]} step={1} value={value.max_chars}
        onChange={e => onChange({ ...value, max_chars: Number(e.target.value) })} />
    </label>
    <label>{tr("subtitleMinSeconds")}
      <input type="number" inputMode="decimal" min={subtitleLimits.min_seconds[0]} max={subtitleLimits.min_seconds[1]} step={0.5} value={value.min_seconds}
        onChange={e => onChange({ ...value, min_seconds: Number(e.target.value) })} />
    </label>
    <button type="button" className="text-button" onClick={() => onChange(defaultSubtitle())} disabled={value.max_chars === 84 && value.min_seconds === 1}>{tr("subtitleReset")}</button>
    <small>{tr("subtitleHelp")}</small>
    {!ok && <small role="alert" className="video-bad">{tr("subtitleInvalid")}</small>}
  </fieldset>;
}
