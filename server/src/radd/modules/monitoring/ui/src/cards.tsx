import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export function Card({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-subtle bg-surface p-4 shadow-lift">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <Icon size={13} aria-hidden />
        {title}
      </h3>
      {children}
    </section>
  );
}

export function StatRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-[13px] text-fg-secondary">{label}</span>
      <span className="text-[13px] font-medium tabular-nums text-heading">{value}</span>
    </div>
  );
}

