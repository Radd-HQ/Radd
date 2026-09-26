import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * A card surface whose whole body collapses behind its heading — the compact
 * treatment for reading-column sections that are reference material rather
 * than first-glance info (Dependencies, Related links). The count chip keeps
 * the "there IS something here" signal visible while collapsed.
 */
export function CollapsibleCard({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  /** Entry count shown as a chip; omit (or 0) to render no chip. */
  count?: number;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <section className="rounded-xl border border-subtle bg-surface shadow-lift">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-fg-muted hover:text-fg cursor-pointer focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
      >
        <Chevron size={13} aria-hidden />
        {title}
        {count !== undefined && count > 0 && (
          <span className="ml-1 rounded bg-elevated px-1.5 text-[11px] text-fg-secondary">
            {count}
          </span>
        )}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}
