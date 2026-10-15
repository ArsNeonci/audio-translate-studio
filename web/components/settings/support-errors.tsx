"use client";
import { apiFetch } from "@audio/ui";
import { useEffect, useState } from "react";
import { useLanguage } from "@/lib/i18n/language-context";
import type { Job } from "@/lib/shared/job-types";

type Row = { id: string; at: string; run: string; kind: "Workflow #" | "Tool #"; step: string };

async function collect(): Promise<Row[]> {
  const found: Row[] = [];
  for (const [url, kind] of [["/api/jobs", "Workflow #"], ["/api/tools", "Tool #"]] as const) {
    try {
      const data = (await (await apiFetch(url, { cache: "no-store" })).json()) as { jobs?: Job[] };
      for (const job of data.jobs || []) for (const [step, item] of Object.entries(job.steps || {})) {
        const error = item?.error;
        if (item?.state === "FAILED" && error?.error_id) found.push({ id: error.error_id, at: error.failed_at, run: String(job.workflow_no ?? "").padStart(6, "0"), kind, step });
      }
    } catch { /* the list is only a convenience */ }
  }
  found.sort((a, b) => b.at.localeCompare(a.at));
  return found.slice(0, 10);
}

/** Settings → Support: the last failures with their short IDs, so a person can read one out (or photograph it) when asking for help. */
export default function SupportErrors() {
  const { tr, language } = useLanguage();
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => {
    let live = true;
    void collect().then(found => { if (live) setRows(found); });
    return () => { live = false; };
  }, []);
  return <section className="lang-switcher-card" aria-label={tr("supportTitle")}>
    <h2>{tr("supportTitle")}</h2>
    <p>{tr("supportDescription")}</p>
    {rows && !rows.length && <p role="status">{tr("supportNone")}</p>}
    {!!rows?.length && <table><thead><tr><th>{tr("supportCode")}</th><th>{tr("supportWhen")}</th><th>{tr("supportRun")}</th><th>{tr("Stage")}</th></tr></thead>
      <tbody>{rows.map((row, i) => <tr key={`${row.id}-${row.at}-${i}`}><td><strong>{row.id}</strong></td><td>{new Date(row.at).toLocaleString(language === "vi" ? "vi-VN" : "en-US")}</td><td>{tr(row.kind)}{row.run}</td><td>{tr(row.step)}</td></tr>)}</tbody></table>}
  </section>;
}
