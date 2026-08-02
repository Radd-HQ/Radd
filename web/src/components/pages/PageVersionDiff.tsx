import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { pageVersionQuery } from "../../lib/queries";
import { collapseUnchanged, diffLines, diffStats } from "../../lib/line-diff";
import type { Page } from "../../lib/types";
import { Button } from "../Button";
import { Spinner } from "../Spinner";

/**
 * Compare two versions of a page (RADD-720).
 *
 * Versions were storable and restorable but not comparable, which made restore a
 * guess: you could roll back to something you had no way to read the difference
 * of.
 *
 * The CURRENT content is `page.version` and is not in `page_versions` (only
 * previous content is snapshotted), so comparing against it reads from the page
 * itself. That asymmetry is the storage model's, not this component's.
 */
export function PageVersionDiff({
  page,
  from,
  to,
  onBack,
}: {
  page: Page;
  /** Older version number. */
  from: number;
  /** Newer version number, or the page's current version. */
  to: number;
  onBack: () => void;
}) {
  const older = useQuery(pageVersionQuery(page.id, from));
  const newerIsCurrent = to >= page.version;
  const newer = useQuery({ ...pageVersionQuery(page.id, to), enabled: !newerIsCurrent });

  const beforeText = older.data?.body ?? "";
  const afterText = newerIsCurrent ? page.body : (newer.data?.body ?? "");

  const lines = useMemo(() => diffLines(beforeText, afterText), [beforeText, afterText]);
  const rows = useMemo(() => collapseUnchanged(lines), [lines]);
  const stats = diffStats(lines);

  if (older.isPending || (!newerIsCurrent && newer.isPending)) {
    return <Spinner label="Loading versions…" />;
  }

  return (
    <div className="mt-3">
      <div className="mb-2 flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={onBack}>
          <ChevronLeft size={13} aria-hidden />
          Back
        </Button>
        <span className="text-[13px] text-fg-secondary">
          v{from} → {newerIsCurrent ? `v${page.version} (current)` : `v${to}`}
        </span>
        <span className="ml-auto font-mono text-[11px]">
          <span className="text-callout-success-ink">+{stats.added}</span>{" "}
          <span className="text-callout-danger-ink">−{stats.removed}</span>
        </span>
      </div>

      {stats.added === 0 && stats.removed === 0 ? (
        <p className="text-[13px] text-fg-faint">These versions are identical.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-subtle bg-surface">
          <table className="w-full border-collapse font-mono text-[12px]">
            <tbody>
              {rows.map((row, index) =>
                row.op === "skip" ? (
                  <tr key={`skip-${index}`}>
                    <td colSpan={3} className="px-3 py-1 text-center text-[11px] text-fg-faint">
                      … {row.count} unchanged line{row.count === 1 ? "" : "s"} …
                    </td>
                  </tr>
                ) : (
                  <tr
                    key={`${row.op}-${index}`}
                    className={
                      row.op === "add"
                        ? "bg-callout-success-fill"
                        : row.op === "remove"
                          ? "bg-callout-danger-fill"
                          : ""
                    }
                  >
                    <td className="w-10 select-none px-2 text-right align-top text-fg-faint">
                      {row.oldLine ?? ""}
                    </td>
                    <td className="w-10 select-none px-2 text-right align-top text-fg-faint">
                      {row.newLine ?? ""}
                    </td>
                    <td
                      className={
                        "whitespace-pre-wrap px-2 align-top " +
                        (row.op === "add"
                          ? "text-callout-success-ink"
                          : row.op === "remove"
                            ? "text-callout-danger-ink"
                            : "text-fg-secondary")
                      }
                    >
                      <span className="select-none pr-1 opacity-60">
                        {row.op === "add" ? "+" : row.op === "remove" ? "−" : " "}
                      </span>
                      {row.text || " "}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
