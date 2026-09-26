import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/** One titled block of rows, shared by My Work and Portal. `count` is a plain number; `badge` is for a
 *  count WAITING on the reader, which earns the accent. */
export function ListSection({
  icon: Icon,
  title,
  count,
  badge,
  badgeLabel = (n) => `${n} new`,
  empty,
  action,
  children,
}: {
  icon: LucideIcon;
  title: string;
  count: number;
  /** A number that needs attention (unread replies) — accented, not neutral. */
  badge?: number;
  /** What the badge counts, said in words (RADD-1293: a bare "1" over 11 rows
   *  read as the total). Defaults to "{n} new". */
  badgeLabel?: (n: number) => string;
  /** Shown instead of the list when `count` is 0. Omit to render nothing at
   *  all: a requester's page should not be a column of "nothing here" boxes. */
  empty?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  if (count === 0 && !empty) return null;
  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      <header className="flex items-center gap-1.5">
        <Icon size={12} className="text-fg-muted" aria-hidden />
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
          {title}
        </h2>
        {count > 0 && <span className="text-[11px] text-fg-faint" data-section-count>{count}</span>}
        {badge ? (
          <span className="rounded-full bg-accent px-1.5 text-[10px] font-medium text-black" data-section-badge>
            {badgeLabel(badge)}
          </span>
        ) : null}
        {action && <span className="ml-auto">{action}</span>}
      </header>
      {count === 0 ? (
        <p className="rounded-lg border border-dashed border-subtle px-4 py-3 text-xs text-fg-faint">
          {empty}
        </p>
      ) : (
        <ul className="flex flex-col overflow-hidden rounded-lg border border-subtle bg-surface">
          {children}
        </ul>
      )}
    </section>
  );
}
