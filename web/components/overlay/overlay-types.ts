"use client";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@audio/ui";

/** The picture library and the logo templates (worker/audio_translate/video/overlays.py). Positions are fractions of the frame. */
export type OverlayAsset = { id: string; name: string; width: number; height: number; size: number };
export type OverlayItem = { asset: string; x: number; y: number; w: number; opacity: number };
export type Orientation = "landscape" | "portrait";
export type OverlayTemplate = { id: string; name: string; orientation: Orientation; items: OverlayItem[] };
export type Overlays = { assets: OverlayAsset[]; templates: OverlayTemplate[]; defaults: Partial<Record<Orientation, string>> };

/** The frames the board draws (YouTube's own): the reference size the pixel boxes of the editor speak in. */
export const FRAME: Record<Orientation, { width: number; height: number }> = { landscape: { width: 1920, height: 1080 }, portrait: { width: 1080, height: 1920 } };

export function useOverlays() {
  const [data, setData] = useState<Overlays | null>(null);
  // Asked again after every change; a failed read keeps what the page already shows.
  const reload = useCallback(() => apiFetch("/api/overlays", { cache: "no-store" }).then(r => (r.ok ? r.json() : null)).then((next: Overlays | null) => { if (next) setData(next); }).catch(() => undefined), []);
  useEffect(() => { void reload(); }, [reload]);
  return { data, reload };
}
