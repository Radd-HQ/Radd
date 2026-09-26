import { Check } from "lucide-react";

/** The per-row outcome list both import dialogs show after a write. */
export function ImportResults({ rows }: { rows: { key: string; label: string; outcome: string; failed: boolean }[] }) {
  return (
    <ul className="flex flex-col gap-0.5 text-xs" data-import-results>
      {rows.map((row) => (
        <li key={row.key} className="flex items-center gap-1.5">
          <Check size={12} className={row.failed ? "text-status-danger-ink" : "text-status-success-ink"} aria-hidden />
          <span className="text-fg">{row.label}</span>
          <span className="text-fg-muted">{row.outcome}</span>
        </li>
      ))}
    </ul>
  );
}

/** A checkbox row in an import picker. */
export const pickRowClasses =
  "flex items-start gap-2 rounded-md border border-subtle px-2.5 py-2 text-[13px] hover:bg-surface/60 cursor-pointer";
