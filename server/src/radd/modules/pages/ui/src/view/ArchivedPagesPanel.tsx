import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ExternalLink, Trash2 } from "lucide-react";
import { api, formatDateTime, invalidateEntities, useConfirm, Button, EmptyState, ErrorText, TextField, Entity } from "@radd/plugin-sdk";
import { PageApi, pageUnarchivePath } from "../endpoints";
import { pageLink } from "../links";
import type { Page, PageSummary } from "../types";
import { archivedRows, filterArchivedRows, type ArchivedRow } from "./archived-rows";

interface BulkResult {
  done: string[];
  skipped: { id: string; reason: string }[];
}

/** A space's archive browser (RADD-1228/1249), under `?archived=1` for `page.manage`: search title and
 *  path, open read-only, restore or delete one or a selection. The server answers per page (done /
 *  skipped with a reason) and each reason stays on its row. */
export function ArchivedPagesPanel({
  spaceId,
  spaceSlug,
  rows,
}: {
  spaceId: string;
  spaceSlug: string;
  rows: PageSummary[];
}) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [skipped, setSkipped] = useState<Map<string, string>>(() => new Map());
  const archived = useMemo(() => archivedRows(rows), [rows]);
  const shown = useMemo(() => filterArchivedRows(archived, query), [archived, query]);
  // A selection only ever means rows that still exist — a restored or deleted
  // page leaves the list on refetch and must leave the selection with it.
  const live = useMemo(() => {
    const ids = new Set(archived.map((row) => row.page.id));
    return new Set([...selected].filter((id) => ids.has(id)));
  }, [archived, selected]);
  const allShownSelected = shown.length > 0 && shown.every((row) => live.has(row.page.id));

  const bulk = useMutation({
    mutationFn: ({ action, ids }: { action: "restore" | "delete"; ids: string[] }) =>
      api.post<BulkResult>(`${PageApi.spaces}/${spaceId}/archived/${action}`, { page_ids: ids }),
    onSuccess: (result) => {
      setSkipped(new Map(result.skipped.map((entry) => [entry.id, entry.reason])));
      setSelected((current) => {
        const next = new Set(current);
        for (const id of result.done) next.delete(id);
        return next;
      });
    },
    onSettled: () => void invalidateEntities(queryClient, Entity.page, Entity.docSpace),
  });

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAllShown = () =>
    setSelected((current) => {
      const next = new Set(current);
      if (allShownSelected) shown.forEach((row) => next.delete(row.page.id));
      else shown.forEach((row) => next.add(row.page.id));
      return next;
    });

  const count = live.size;
  const noun = count === 1 ? "page" : "pages";
  const onBulkRestore = async () => {
    const ok = await confirm({
      title: `Restore ${count} ${noun}?`,
      message: "Each goes back where it was archived from; archived ancestors and hidden subpages come back with it.",
      confirmLabel: "Restore",
    });
    if (ok) bulk.mutate({ action: "restore", ids: [...live] });
  };
  const onBulkDelete = async () => {
    const ok = await confirm({
      title: `Delete ${count} ${noun} permanently?`,
      message: "Their history and archived subpages go with them. This cannot be undone. A page with live subpages under it is refused and stays listed.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) bulk.mutate({ action: "delete", ids: [...live] });
  };

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
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="min-w-[16rem] flex-1">
              <TextField
                label="Search archived pages"
                placeholder="Title or path…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                data-archived-search
              />
            </div>
            <label className="flex items-center gap-1.5 self-end pb-2 text-xs text-fg-secondary">
              <input
                type="checkbox"
                checked={allShownSelected}
                onChange={toggleAllShown}
                disabled={shown.length === 0}
                aria-label="Select all shown"
                data-archived-select-all
              />
              Select all shown
            </label>
          </div>
          {count > 0 && (
            <div
              className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-strong bg-elevated px-3 py-2"
            >
              <span className="text-xs font-medium text-heading" data-archived-selected-count>
                {count} selected
              </span>
              <Button size="sm" variant="secondary" onClick={() => void onBulkRestore()} disabled={bulk.isPending} data-archived-bulk-restore>
                <ArchiveRestore size={13} aria-hidden />
                Restore
              </Button>
              <Button size="sm" variant="danger" onClick={() => void onBulkDelete()} disabled={bulk.isPending} data-archived-bulk-delete>
                <Trash2 size={13} aria-hidden />
                Delete permanently
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} disabled={bulk.isPending}>
                Clear
              </Button>
              {bulk.isPending && <span className="text-xs text-fg-muted">Working…</span>}
              {bulk.isError && <ErrorText className="basis-full" error={bulk.error} />}
            </div>
          )}
          {shown.length === 0 ? (
            <p className="text-[13px] text-fg-faint" data-archived-no-match>
              No archived page matches “{query}”.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {shown.map((row) => (
                <ArchivedPageRow
                  key={row.page.id}
                  row={row}
                  spaceSlug={spaceSlug}
                  selected={live.has(row.page.id)}
                  onToggle={() => toggle(row.page.id)}
                  skippedReason={skipped.get(row.page.id)}
                />
              ))}
            </ul>
          )}
        </>
      )}
      {confirmDialog}
    </section>
  );
}

function ArchivedPageRow({
  row,
  spaceSlug,
  selected,
  onToggle,
  skippedReason,
}: {
  row: ArchivedRow;
  spaceSlug: string;
  selected: boolean;
  onToggle: () => void;
  skippedReason?: string;
}) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [restored, setRestored] = useState(false);
  const restore = useMutation({
    mutationFn: () => api.post<Page>(pageUnarchivePath(row.page.id)),
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
      className={
        "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-2 " +
        (selected ? "border-strong bg-elevated" : "border-subtle bg-surface/50")
      }
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        aria-label={`Select ${page.title}`}
        data-archived-select
      />
      <div className="min-w-0 flex-1">
        <Link
          {...pageLink(spaceSlug, page.path)}
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
        {skippedReason && (
          <p className="mt-1 text-[11px] text-status-danger-ink" data-archived-skipped>
            Skipped: {skippedReason}
          </p>
        )}
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
