import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Link2 } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { pageBacklinksQuery } from "../../lib/queries";
import { relativeTime } from "../../lib/dates";

/**
 * "What links to this page" (RADD-713), below the body on every page.
 *
 * Renders NOTHING when there are no backlinks. A permanent empty "Linked from"
 * heading on the majority of pages is chrome, not information — the panel
 * should appear when it has something to say.
 */
export function PageBacklinksPanel({ pageId }: { pageId: string }) {
  const { data } = useQuery(pageBacklinksQuery(pageId));
  if (!data?.length) return null;
  return (
    <section className="mt-6 border-t border-subtle pt-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <Link2 size={12} aria-hidden />
        Linked from
        <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
          {data.length}
        </span>
      </h3>
      <ul className="flex flex-col gap-1">
        {data.map((page) => (
          <li key={page.id} className="flex items-baseline gap-2">
            <Link
              to={RoutePath.page}
              params={{ spaceSlug: page.space_slug, pageSlug: page.slug }}
              className="text-[13px] text-accent-text hover:underline"
            >
              {page.title}
            </Link>
            <span className="text-[11px] text-fg-faint" title={page.updated_at}>
              {relativeTime(page.updated_at)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
