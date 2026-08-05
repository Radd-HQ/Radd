import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * One band of mapping rows (spec 100).
 *
 * The rule every mapping table follows: what the project actually USES is
 * expanded, everything else is collapsed AND already set to ignore — with the
 * reason on the row, so hiding it is a judgement you can overrule rather than a
 * disappearance. A live Jira exposes 337 fields, 59 issue types and 83 statuses;
 * a project uses a handful of each.
 */
export function MappingSection({
  title,
  hint,
  count,
  defaultOpen = false,
  forceOpen = false,
  children,
}: {
  title: string;
  hint?: string;
  count: number;
  defaultOpen?: boolean;
  /** Held open regardless of the toggle — a band filter (RADD-882) must never
   * hide its matches behind a collapsed fold (the cycles-page rule). */
  forceOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = open || forceOpen;
  if (count === 0) return null;
  return (
    <div className="rounded-lg border border-subtle">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={isOpen}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface/60 cursor-pointer"
      >
        {isOpen ? (
          <ChevronDown size={14} className="shrink-0 text-fg-muted" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-fg-muted" />
        )}
        <span className="text-[13px] font-medium text-fg">{title}</span>
        <span className="rounded bg-elevated px-1.5 text-[11px] text-fg-secondary">{count}</span>
        {hint && <span className="ml-2 truncate text-xs text-fg-faint">{hint}</span>}
      </button>
      {isOpen && (
        <div className="divide-y divide-subtle/60 border-t border-subtle">{children}</div>
      )}
    </div>
  );
}

/** A row's identity column: the Jira value plus how much of the project uses it. */
export function RowLabel({
  value,
  count,
  detail,
  reason,
}: {
  value: string;
  count?: number;
  detail?: string;
  reason?: string;
}) {
  return (
    <div className="min-w-0 flex-1">
      <p className="truncate text-[13px] text-fg">
        {value}
        {count !== undefined && (
          <span className="ml-1.5 text-xs text-fg-faint">
            {count === 0 ? "unused" : `${count} issue${count === 1 ? "" : "s"}`}
          </span>
        )}
      </p>
      {/* WHY this row is where it is — shown so a collapsed row can be argued with. */}
      {reason && (
        <p className="truncate text-xs text-fg-muted" title={reason}>
          {reason}
        </p>
      )}
      {detail && <p className="truncate text-xs text-fg-faint">{detail}</p>}
    </div>
  );
}

/** Split rows into "the project uses these" and "it does not". */
export function splitByUse<T extends { count: number }>(rows: T[]): [T[], T[]] {
  return [rows.filter((r) => r.count > 0), rows.filter((r) => r.count === 0)];
}
