import { isTranslationMode, type TranslationMode } from "@/lib/shared/translation-modes";
import { subtitleValid, type SubtitleSettings } from "@/components/video/subtitle-options";

/** The Studio form as the person left it: the choices that describe HOW to work, never what to work on (no link, audio file or video clips).
 *  Kept in the browser of the app (localStorage). Anything missing, unreadable or no longer valid simply gives the usual defaults. */
export type Remembered = {
  voice?: string; style?: string; address?: string; mode?: TranslationMode; manual?: boolean; subtitle?: SubtitleSettings;
  video?: { resolution?: string; quality?: string; overlay?: string; burn?: boolean; ultra?: boolean };
};

const KEY = "audio-studio-settings-v1";
const RESOLUTIONS = ["keep", "1080", "720", "480"], QUALITIES = ["high", "medium", "light"];
const text = (value: unknown) => (typeof value === "string" && value.length > 0 && value.length <= 80 ? value : undefined);
const flag = (value: unknown) => (typeof value === "boolean" ? value : undefined);

/** What was left, checked field by field; null when there is nothing usable. */
export function loadRemembered(): Remembered | null {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "null");
    if (!raw || typeof raw !== "object") return null;
    const subtitle = raw.subtitle && typeof raw.subtitle === "object" ? { max_chars: Number(raw.subtitle.max_chars), min_seconds: Number(raw.subtitle.min_seconds) } : undefined;
    const video = raw.video && typeof raw.video === "object" ? raw.video : {};
    return {
      voice: text(raw.voice), style: text(raw.style), address: text(raw.address), mode: isTranslationMode(raw.mode) ? raw.mode : undefined, manual: flag(raw.manual),
      subtitle: subtitle && subtitleValid(subtitle) ? subtitle : undefined,
      video: {
        resolution: RESOLUTIONS.includes(video.resolution) ? video.resolution : undefined, quality: QUALITIES.includes(video.quality) ? video.quality : undefined,
        overlay: typeof video.overlay === "string" && video.overlay.length <= 40 ? video.overlay : undefined, burn: flag(video.burn), ultra: flag(video.ultra),
      },
    };
  } catch { return null; }
}

/** Saves the fields given; a field left out (undefined or empty) keeps what was saved before. Never throws (private window, blocked storage). */
export function saveRemembered(next: Remembered) {
  try {
    const before = loadRemembered() || {};
    const keep = <T,>(value: T | undefined | "", old: T | undefined) => (value === undefined || value === "" ? old : value);
    localStorage.setItem(KEY, JSON.stringify({
      voice: keep(next.voice, before.voice), style: keep(next.style, before.style), address: keep(next.address, before.address),
      mode: next.mode ?? before.mode, manual: next.manual ?? before.manual, subtitle: next.subtitle ?? before.subtitle, video: { ...before.video, ...next.video },
    }));
  } catch { /* nothing to do: the form just starts from the defaults next time */ }
}
