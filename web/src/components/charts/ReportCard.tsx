import type { ReactNode } from "react";

interface ReportCardProps {
  title: string;
  description?: string;
  /** Controls rendered at the top-right (date range, interval toggle, pickers). */
  controls?: ReactNode;
  /** A line under the description — the cross-project scope note (RADD-789). */
  note?: ReactNode;
  children: ReactNode;
}

/** Titled panel wrapping one report chart/table on the dashboards (spec 19). */
export function ReportCard({ title, description, controls, note, children }: ReportCardProps) {
  return (
    <section className="rounded-lg border border-subtle bg-surface/30">
      <header className="flex flex-wrap items-start gap-x-4 gap-y-2 border-b border-subtle px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-heading">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-fg-muted">{description}</p>}
          {note}
        </div>
        {controls && <div className="ml-auto flex flex-wrap items-center gap-2">{controls}</div>}
      </header>
      <div className="px-4 py-4">{children}</div>
    </section>
  );
}
