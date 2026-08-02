import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { FolderTree } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { pagesQuery } from "../../lib/queries";
import { splitExtensionBlocks } from "../../lib/page-extensions";
import { relativeTime } from "../../lib/dates";

/** Extensions that already list what is beneath a page. */
const INDEXING = new Set(["toc", "children", "label-list"]);

/**
 * "What is under this page", below the body (RADD-714).
 *
 * A section landing page whose children are only visible in a 250px tree rail is
 * a dead end for anyone who arrived from search or a link — which is most
 * arrivals. This makes the subtree part of the page.
 *
 * **The extension wins.** If the author placed a `toc`, `children` or
 * `label-list` block, they have said where they want the index and this stays
 * out of the way: an explicit choice beats a default, and two lists of the same
 * children on one page is worse than none.
 */
export function PageChildIndex({
  pageId,
  spaceId,
  spaceSlug,
  body,
}: {
  pageId: string;
  spaceId: string;
  spaceSlug: string;
  body: string;
}) {
  const { data: rows } = useQuery(pagesQuery(spaceId));
  const authorPlacedOne = splitExtensionBlocks(body).some(
    (segment) => segment.kind === "extension" && INDEXING.has(segment.name),
  );
  const children = (rows ?? []).filter((row) => row.parent_id === pageId);

  if (authorPlacedOne || children.length === 0) return null;

  return (
    <section className="mt-6 border-t border-subtle pt-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <FolderTree size={12} aria-hidden />
        In this section
        <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
          {children.length}
        </span>
      </h3>
      <ul className="grid gap-1 sm:grid-cols-2">
        {children.map((child) => (
          <li key={child.id}>
            <Link
              to={RoutePath.page}
              params={{ spaceSlug, pageSlug: child.slug }}
              className="flex items-baseline justify-between gap-2 rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5 hover:border-strong"
            >
              <span className="min-w-0 truncate text-[13px] text-fg">{child.title}</span>
              <span className="shrink-0 text-[11px] text-fg-faint" title={child.updated_at}>
                {relativeTime(child.updated_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
