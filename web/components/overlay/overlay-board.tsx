"use client";
import { apiUrl } from "@audio/ui";
import { useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import { FRAME, type OverlayAsset, type OverlayItem, type Orientation } from "@/components/overlay/overlay-types";

const SNAP = 0.012;          // how close (as a fraction of the frame) an edge or the middle pulls the picture in
const MIN_WIDTH = 0.02;
const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), Math.max(low, high));

/** A picture's height as a fraction of the frame's height, from its width fraction and its own proportions. */
export function heightOf(item: OverlayItem, asset: OverlayAsset | undefined, orientation: Orientation) {
  const { width, height } = FRAME[orientation];
  return asset ? item.w * width * (asset.height / asset.width) / height : item.w;
}

/** Keep a picture whole inside the frame: its corner and its width are limited so that no edge goes outside. */
export function fit(item: OverlayItem, asset: OverlayAsset | undefined, orientation: Orientation): OverlayItem {
  const { width, height } = FRAME[orientation];
  const ratio = asset ? (asset.height / asset.width) * width / height : 1;           // height fraction per width fraction
  const w = clamp(item.w, MIN_WIDTH, Math.min(1 - item.x, (1 - item.y) / ratio));
  return { ...item, w: Math.round(w * 1e5) / 1e5, x: Math.round(clamp(item.x, 0, 1 - w) * 1e5) / 1e5, y: Math.round(clamp(item.y, 0, 1 - w * ratio) * 1e5) / 1e5 };
}

type Drag = { index: number; mode: "move" | "resize"; startX: number; startY: number; item: OverlayItem };

/** The frame the logos are placed on: drag to move, the corner square to resize, the arrow keys for single pixels, Delete to take one off. */
export default function OverlayBoard({ orientation, items, assets, selected, onSelect, onChange, onRemove }:
  { orientation: Orientation; items: OverlayItem[]; assets: OverlayAsset[]; selected: number | null; onSelect: (index: number | null) => void;
    onChange: (next: OverlayItem[]) => void; onRemove: (index: number) => void }) {
  const { tr } = useLanguage();
  const board = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [guides, setGuides] = useState<{ x: boolean; y: boolean }>({ x: false, y: false });
  const find = (id: string) => assets.find(asset => asset.id === id);
  const replace = (index: number, item: OverlayItem) => onChange(items.map((current, i) => i === index ? item : current));

  function start(event: React.PointerEvent, index: number, mode: Drag["mode"]) {
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { index, mode, startX: event.clientX, startY: event.clientY, item: items[index] };
    onSelect(index);
  }

  function move(event: React.PointerEvent) {
    const state = drag.current, rect = board.current?.getBoundingClientRect();
    if (!state || !rect) return;
    const dx = (event.clientX - state.startX) / rect.width, dy = (event.clientY - state.startY) / rect.height;
    const asset = find(state.item.asset);
    if (state.mode === "resize") { replace(state.index, fit({ ...state.item, w: state.item.w + dx }, asset, orientation)); return; }
    const moved = fit({ ...state.item, x: state.item.x + dx, y: state.item.y + dy }, asset, orientation);
    const high = heightOf(moved, asset, orientation);
    // Pull to an edge or the middle when close, and show the line it snapped to.
    const snapX = [0, 1 - moved.w, (1 - moved.w) / 2].find(target => Math.abs(moved.x - target) < SNAP);
    const snapY = [0, 1 - high, (1 - high) / 2].find(target => Math.abs(moved.y - target) < SNAP);
    setGuides({ x: snapX !== undefined, y: snapY !== undefined });
    replace(state.index, { ...moved, x: snapX ?? moved.x, y: snapY ?? moved.y });
  }

  function stop() { drag.current = null; setGuides({ x: false, y: false }); }

  function key(event: React.KeyboardEvent, index: number) {
    const item = items[index], { width, height } = FRAME[orientation], step = event.shiftKey ? 10 : 1;
    const by: Record<string, [number, number]> = { ArrowLeft: [-step / width, 0], ArrowRight: [step / width, 0], ArrowUp: [0, -step / height], ArrowDown: [0, step / height] };
    if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); onRemove(index); return; }
    if (!by[event.key]) return;
    event.preventDefault();
    replace(index, fit({ ...item, x: item.x + by[event.key][0], y: item.y + by[event.key][1] }, find(item.asset), orientation));
  }

  return <div className="overlay-stage">
    <div ref={board} className={`overlay-board ${orientation}`} role="group" aria-label={tr("overlaysBoard")} onPointerDown={() => onSelect(null)} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop}>
      <div className="overlay-subzone" aria-hidden="true"><span>{tr("overlaysSubtitleZone")}</span></div>
      {guides.x && <i className="overlay-guide vertical" aria-hidden="true" />}
      {guides.y && <i className="overlay-guide horizontal" aria-hidden="true" />}
      {items.map((item, index) => {
        const asset = find(item.asset);
        return <div key={`${item.asset}-${index}`} className={`overlay-item${selected === index ? " selected" : ""}`} tabIndex={0} role="button" aria-pressed={selected === index}
          aria-label={tr("overlaysItem", { name: asset?.name || "" })} style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%`, width: `${item.w * 100}%` }}
          onPointerDown={event => start(event, index, "move")} onFocus={() => onSelect(index)} onKeyDown={event => key(event, index)}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a local API picture, drawn at its own proportions */}
          <img src={apiUrl(`/api/overlays/assets/${item.asset}`)} alt="" draggable={false} style={{ opacity: item.opacity }} />
          {selected === index && <span className="overlay-handle" aria-hidden="true" onPointerDown={event => start(event, index, "resize")} />}
        </div>;
      })}
      {!items.length && <p className="overlay-board-empty">{tr("overlaysBoardEmpty")}</p>}
    </div>
    <small>{tr("overlaysBoardHelp")}</small>
  </div>;
}
