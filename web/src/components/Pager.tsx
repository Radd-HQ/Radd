/** Classic pagination (pagination wave, 2026-08-01): first/prev, a windowed
 *  page-number strip, next/last, and the true total — replaces the append-only
 *  "Load more" on every paged item surface. `pageCount` may be null while the
 *  count is still loading (arrows render, numbers wait). `compact` drops the
 *  number strip and total for narrow homes (the roadmap tray). */

import {
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Select } from "./Select";

/** Window of page numbers around the current page: 1 … 4 [5] 6 … 42. */
function pageWindow(page: number, pageCount: number): (number | "…")[] {
  if (pageCount <= 7) return Array.from({ length: pageCount }, (_, i) => i + 1);
  const around = [page - 1, page, page + 1].filter((p) => p > 1 && p < pageCount);
  const out: (number | "…")[] = [1];
  if (around[0] !== undefined && around[0] > 2) out.push("…");
  out.push(...around);
  if (around.length > 0 && around[around.length - 1] < pageCount - 1) out.push("…");
  out.push(pageCount);
  return out;
}

export function Pager({
  page,
  pageCount,
  total,
  onPage,
  compact = false,
  pageSize,
  pageSizes,
  onPageSize,
}: {
  /** 1-based current page. */
  page: number;
  /** Total pages, or null while unknown (count still loading). */
  pageCount: number | null;
  /** Total items, or null while unknown. */
  total?: number | null;
  onPage: (page: number) => void;
  compact?: boolean;
  /** RADD-1177: when all three are given, a per-page size picker follows the
   *  total. The caller owns the choice (personal, remembered per browser). */
  pageSize?: number;
  pageSizes?: readonly number[];
  onPageSize?: (size: number) => void;
}) {
  const last = pageCount ?? Math.max(page, 1);
  const canPrev = page > 1;
  const canNext = pageCount === null ? true : page < pageCount;
  const navClasses =
    "flex h-6 w-6 items-center justify-center rounded-md border border-strong text-fg-secondary " +
    "hover:border-emphasis hover:text-fg cursor-pointer disabled:opacity-40 disabled:pointer-events-none";

  return (
    <nav className="flex items-center gap-1" aria-label="Pagination">
      <button type="button" aria-label="First page" title="First page" className={navClasses}
        disabled={!canPrev} onClick={() => onPage(1)}>
        <ChevronFirst size={13} aria-hidden />
      </button>
      <button type="button" aria-label="Previous page" title="Previous page" className={navClasses}
        disabled={!canPrev} onClick={() => onPage(page - 1)}>
        <ChevronLeft size={13} aria-hidden />
      </button>
      {compact || pageCount === null ? (
        <span className="px-1.5 text-xs tabular-nums text-fg-secondary">
          {page}
          {pageCount !== null && ` / ${pageCount}`}
        </span>
      ) : (
        pageWindow(page, pageCount).map((entry, i) =>
          entry === "…" ? (
            <span key={`gap-${i}`} className="px-0.5 text-xs text-fg-faint" aria-hidden>
              …
            </span>
          ) : (
            <button
              key={entry}
              type="button"
              aria-label={`Page ${entry}`}
              aria-current={entry === page ? "page" : undefined}
              onClick={() => onPage(entry)}
              className={`h-6 min-w-6 rounded-md border px-1 text-xs tabular-nums cursor-pointer ${
                entry === page
                  ? "border-accent/60 bg-accent/15 text-accent-text"
                  : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg"
              }`}
            >
              {entry}
            </button>
          ),
        )
      )}
      <button type="button" aria-label="Next page" title="Next page" className={navClasses}
        disabled={!canNext} onClick={() => onPage(page + 1)}>
        <ChevronRight size={13} aria-hidden />
      </button>
      <button type="button" aria-label="Last page" title="Last page" className={navClasses}
        disabled={pageCount === null || page >= last} onClick={() => onPage(last)}>
        <ChevronLast size={13} aria-hidden />
      </button>
      {!compact && total != null && (
        <span className="ml-2 text-xs text-fg-faint">{total.toLocaleString()} issues</span>
      )}
      {!compact && pageSize !== undefined && pageSizes && onPageSize && (
        <span className="ml-2 flex items-center gap-1 text-xs text-fg-faint" data-page-size>
          <Select
            size="sm"
            value={String(pageSize)}
            onChange={(value) => onPageSize(Number(value))}
            options={pageSizes.map((size) => ({ value: String(size), label: String(size) }))}
          />
          per page
        </span>
      )}
    </nav>
  );
}
