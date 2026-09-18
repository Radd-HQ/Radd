import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { pageLink } from "../../lib/page-links";
import { pagesQuery } from "../../lib/queries";
import { Popover } from "../Popover";
import type { PageBreadcrumb } from "../../lib/types";

/**
 * One breadcrumb segment, with its SIBLINGS behind a chevron (RADD-714).
 *
 * A trail alone tells you where you are; siblings tell you what else is at this
 * level, which is the question that otherwise sends you hunting in the tree.
 * Confluence and every file manager work this way for the same reason.
 */
export function BreadcrumbCrumb({
  crumb,
  spaceId,
  spaceSlug,
}: {
  crumb: PageBreadcrumb;
  spaceId: string;
  spaceSlug: string;
}) {
  const [open, setOpen] = useState(false);
  const { data: rows } = useQuery({ ...pagesQuery(spaceId), enabled: open });

  const self = rows?.find((row) => row.id === crumb.id);
  const siblings = (rows ?? []).filter(
    (row) => row.parent_id === (self?.parent_id ?? null) && row.id !== crumb.id,
  );

  return (
    <span className="relative flex min-w-0 items-center">
      <Link
        {...pageLink(spaceSlug, crumb.path)}
        className="truncate text-fg-secondary hover:text-fg"
      >
        {crumb.title}
      </Link>
      <button
        type="button"
        onClick={() => setOpen((on) => !on)}
        aria-label={`Pages beside ${crumb.title}`}
        aria-expanded={open}
        className="ml-0.5 rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
      >
        <ChevronDown size={11} aria-hidden />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        label={`Pages beside ${crumb.title}`}
        align="start"
        className="max-h-72 w-56 overflow-y-auto py-1"
      >
        {siblings.length === 0 ? (
          <p className="px-3 py-1.5 text-[12px] text-fg-faint">Nothing else at this level.</p>
        ) : (
          siblings.map((sibling) => (
            <Link
              key={sibling.id}
              {...pageLink(spaceSlug, sibling.path)}
              onClick={() => setOpen(false)}
              className="block truncate px-3 py-1.5 text-[13px] text-fg hover:bg-elevated"
            >
              {sibling.title}
            </Link>
          ))
        )}
      </Popover>
    </span>
  );
}
