"use client";
import { useLanguage } from "@/lib/i18n/language-context";

/** One row: what is shown of a chosen file, and whether it is in trouble. */
export type OrderedFile = { key: string; name: string; title?: string; detail?: string; bad?: boolean };

/** The chosen files in their order, each with ↑ ↓ ✕: the videos of a merge, the parts of a translation. The order is the caller's state. */
export default function OrderedFileList({ items, onChange, disabled }: { items: OrderedFile[]; onChange: (next: OrderedFile[]) => void; disabled?: boolean }) {
  const { tr } = useLanguage();
  if (!items.length) return null;
  const move = (index: number, by: number) => {
    const next = [...items]; const [item] = next.splice(index, 1); next.splice(index + by, 0, item); onChange(next);
  };
  return <ol className="video-list">{items.map((item, index) => <li key={item.key} className={item.bad ? "video-bad" : undefined}>
    <span className="video-name" title={item.title || item.name}>{item.name}</span>
    {item.detail && <small>{item.detail}</small>}
    <span className="video-actions">
      <button type="button" className="text-button" aria-label={tr("videoUp")} title={tr("videoUp")} disabled={disabled || index === 0} onClick={() => move(index, -1)}>↑</button>
      <button type="button" className="text-button" aria-label={tr("videoDown")} title={tr("videoDown")} disabled={disabled || index === items.length - 1} onClick={() => move(index, 1)}>↓</button>
      <button type="button" className="text-button" aria-label={tr("videoRemove")} title={tr("videoRemove")} disabled={disabled} onClick={() => onChange(items.filter((_, i) => i !== index))}>✕</button>
    </span>
  </li>)}</ol>;
}

/** File names in the order a person expects: part-2 before part-10. */
export const byName = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
