import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/**
 * One titled block of rows — the section chrome My Work and Portal share
 * (RADD-799).
 *
 * Hussein's read was that My Work looked messy while Portal's grouped sections
 * read well, and the difference was not the content: My Work's headings were
 * 14px semibold body text, Portal's were 11px uppercase muted labels. Two
 * heading styles on two pages showing the same kind of list is what "messy"
 * meant. This is Portal's, extracted, so both pages use the one object.
 *
 * `count` is rendered as a plain number rather than a badge; `badge` is for a
 * count that means something is WAITING on the reader, which earns the accent.
 */
export function ListSection({
  icon: Icon,
  title,
  count,
  badge,
  empty,
  action,
  children,
}: {
  icon: LucideIcon;
  title: string;
  count: number;
  /** A number that needs attention (unread replies) — accented, not neutral. */
  badge?: number;
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
        {badge ? (
          <span className="rounded-full bg-accent px-1.5 text-[10px] font-medium text-black">
            {badge}
          </span>
        ) : (
          count > 0 && <span className="text-[11px] text-fg-faint">{count}</span>
        )}
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
