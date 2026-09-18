import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ExternalLink } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { RoutePath, apiPageUnarchivePath } from "../../lib/constants";
import { formatDateTime } from "../../lib/dates";
import type { Page, PageSummary } from "../../lib/types";
import { Button } from "../Button";
import { useConfirm } from "../ConfirmDialog";
import { EmptyState } from "../EmptyState";
import { ErrorText } from "../ErrorText";
import { comparePagesNaturally } from "./PageTree";

/** One archived page as the browser lists it: where it lived, when it went,
 * and what went with it. */
export interface ArchivedRow {
  page: PageSummary;
  /** Ancestor titles, root first — the path it was archived from. */
  path: string[];
  /** Archived ancestors — restoring this page restores them too. */
  archivedAncestors: PageSummary[];
  /** Descendants hidden with it (any state): what comes back on restore. */
  hiddenBelow: number;
}

/** Pure: the `include_archived` listing → the archive browser's rows. A page
 * is listed when IT is archived; a live descendant hidden under an archived
 * ancestor is not a row — it rides along with the ancestor's restore. */
export function archivedRows(rows: PageSummary[]): ArchivedRow[] {
  const byId = new Map(rows.map((row) => [row.id, row]));
  const childrenOf = new Map<string | null, PageSummary[]>();
  for (const row of rows) {
    const siblings = childrenOf.get(row.parent_id) ?? [];
    siblings.push(row);
    childrenOf.set(row.parent_id, siblings);
  }
  const countBelow = (id: string): number => {
    let total = 0;
    const queue = [...(childrenOf.get(id) ?? [])];
    for (let guard = 0; queue.length && guard < rows.length; guard++) {
      const next = queue.shift()!;
      total += 1;
      queue.push(...(childrenOf.get(next.id) ?? []));
    }
    return total;
  };
  const out: ArchivedRow[] = [];
  for (const page of rows) {
    if (!page.archived_at) continue;
    const path: string[] = [];
    const archivedAncestors: PageSummary[] = [];
    let cursor = page.parent_id ? byId.get(page.parent_id) : undefined;
    for (let guard = 0; cursor && guard < rows.length; guard++) {
      path.unshift(cursor.title);
      if (cursor.archived_at) archivedAncestors.unshift(cursor);
      cursor = cursor.parent_id ? byId.get(cursor.parent_id) : undefined;
    }
    out.push({ page, path, archivedAncestors, hiddenBelow: countBelow(page.id) });
  }
  // Most recently archived first — "what did I just lose" is the usual question.
  return out.sort(
    (a, b) =>
      (b.page.archived_at ?? "").localeCompare(a.page.archived_at ?? "") ||
      comparePagesNaturally(a.page, b.page),
  );
}

/**
 * The archive browser for one space (RADD-1228, GitHub #7): every archived
 * page, openable read-only and restorable from here — the UI half of what the
 * API has offered since spec 43. Rendered in the space's content pane under
 * `?archived=1`, for holders of `page.manage` (the listing's own gate).
 */
export function ArchivedPagesPanel({ spaceSlug, rows }: { spaceSlug: string; rows: PageSummary[] }) {
  const archived = useMemo(() => archivedRows(rows), [rows]);
  return (
    <section aria-label="Archived pages" data-archived-pages className="px-6 py-5">
      <div className="mb-1 flex items-center gap-2">
        <Archive size={15} className="text-fg-muted" aria-hidden />
        <h2 className="text-base font-semibold text-heading">Archived pages</h2>
        <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
          {archived.length}
        </span>
      </div>
      <p className="mb-4 text-xs text-fg-muted">
        Hidden from the tree, kept with their history. Open one to read it, or restore it to
        put it back where it was — subpages come back with it.
      </p>
      {archived.length === 0 ? (
        <EmptyState icon={Archive} message="Nothing is archived in this space." />
      ) : (
        <ul className="flex flex-col gap-2">
          {archived.map((row) => (
            <ArchivedPageRow key={row.page.id} row={row} spaceSlug={spaceSlug} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ArchivedPageRow({ row, spaceSlug }: { row: ArchivedRow; spaceSlug: string }) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [restored, setRestored] = useState(false);
  const restore = useMutation({
    mutationFn: () => api.post<Page>(apiPageUnarchivePath(row.page.id)),
    onSuccess: () => setRestored(true),
    onSettled: () => void invalidateEntities(queryClient, Entity.page, Entity.docSpace),
  });
  const { page, path, archivedAncestors, hiddenBelow } = row;
  const onRestore = async () => {
    if (archivedAncestors.length > 0) {
      const names = archivedAncestors.map((a) => `“${a.title}”`).join(", ");
      const ok = await confirm({
        title: `Restore “${page.title}”?`,
        message: `It sits under archived ${archivedAncestors.length === 1 ? "page" : "pages"} ${names}, which will be restored with it so it is reachable again.`,
        confirmLabel: "Restore",
      });
      if (!ok) return;
    }
    restore.mutate();
  };
  return (
    <li
      data-archived-page={page.id}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-subtle bg-surface/50 px-3 py-2"
    >
      <div className="min-w-0 flex-1">
        <Link
          to={RoutePath.page}
          params={{ spaceSlug, pageSlug: page.slug }}
          className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-heading hover:underline"
        >
          <span className="min-w-0 truncate">{page.title}</span>
          <ExternalLink size={11} className="shrink-0 text-fg-faint" aria-hidden />
        </Link>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-fg-muted">
          <span className="min-w-0 truncate">{path.length ? path.join(" / ") : "Top level"}</span>
          <span aria-hidden>·</span>
          <span>Archived {page.archived_at ? formatDateTime(page.archived_at) : ""}</span>
          {hiddenBelow > 0 && (
            <>
              <span aria-hidden>·</span>
              <span>
                {hiddenBelow} {hiddenBelow === 1 ? "subpage" : "subpages"}
              </span>
            </>
          )}
        </div>
      </div>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => void onRestore()}
        disabled={restore.isPending || restored}
      >
        <ArchiveRestore size={13} aria-hidden />
        {restore.isPending ? "Restoring…" : restored ? "Restored" : "Restore"}
      </Button>
      {restore.isError && <ErrorText className="basis-full" error={restore.error} />}
      {confirmDialog}
    </li>
  );
}
