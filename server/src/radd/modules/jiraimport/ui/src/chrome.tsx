import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, CircleAlert, Loader2, type LucideIcon } from "lucide-react";

/** One section of the import page. `section` is the `data-jira-section` proof hook. */
export function Panel({
  section,
  id,
  title,
  description,
  action,
  children,
}: {
  section: string;
  id?: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} className="rounded-lg border border-subtle bg-surface p-4" data-jira-section={section}>
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium text-heading">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-fg-secondary">{description}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

const TONES = {
  success: ["text-status-success-ink", CheckCircle2],
  warning: ["text-status-warning-ink", AlertTriangle],
  danger: ["text-status-danger-ink", CircleAlert],
  running: ["text-fg-secondary", Loader2],
} as const satisfies Record<string, readonly [string, LucideIcon]>;

/** A status line: the tone picks the ink and the icon (`running` spins). */
export function StatusText({
  tone,
  icon,
  wrap = false,
  children,
}: {
  tone: keyof typeof TONES;
  icon?: LucideIcon;
  /** Let the text wrap (a status cell in a wide row); default one line. */
  wrap?: boolean;
  children: ReactNode;
}) {
  const [ink, ToneIcon] = TONES[tone];
  const Icon = icon ?? ToneIcon;
  return (
    <span className={`flex items-center gap-1.5 ${wrap ? "" : "whitespace-nowrap "}text-xs ${ink}`}>
      <Icon size={13} className={tone === "running" ? "animate-spin" : undefined} /> {children}
    </span>
  );
}

/** "12 issues cached · 3 comments recovered" — the non-zero counts, in the order `labels` lists them. */
export function CountList({
  counts,
  labels,
  empty,
}: {
  counts: Record<string, number>;
  labels: [string, string][];
  empty?: string;
}) {
  const shown = labels.filter(([key]) => (counts[key] ?? 0) > 0);
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-secondary">
      {shown.map(([key, label]) => (
        <span key={key}>
          <span className="text-heading">{counts[key]}</span> {label}
        </span>
      ))}
      {empty && shown.length === 0 && <span className="text-fg-faint">{empty}</span>}
    </div>
  );
}
