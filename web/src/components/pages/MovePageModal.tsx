import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CornerLeftUp } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiPagePath } from "../../lib/constants";
import type { Page, PageUpdate } from "../../lib/types";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";
import { ListSearchInput } from "../ListSearchInput";
import { Modal } from "../Modal";
import { comparePagesNaturally } from "./PageTree";

/** The rows the tree already holds — enough to pick a parent from. */
interface MoveRow {
  id: string;
  parent_id: string | null;
  title: string;
}

/** The dropdown render cap, the TokenMultiSelect convention (RADD-881). */
const MAX_VISIBLE = 50;

/** Every page under `rootId`, itself included — the set that cannot become its parent. */
export function subtreeIds(rows: MoveRow[], rootId: string): Set<string> {
  const childrenOf = new Map<string | null, string[]>();
  for (const row of rows) {
    const list = childrenOf.get(row.parent_id) ?? [];
    list.push(row.id);
    childrenOf.set(row.parent_id, list);
  }
  const out = new Set<string>([rootId]);
  const queue = [rootId];
  // Bounded by the row count: a cycle is impossible (the server refuses one)
  // but a bad row must not hang the picker.
  for (let guard = 0; queue.length && guard < rows.length; guard++) {
    const next = queue.shift()!;
    for (const child of childrenOf.get(next) ?? []) {
      if (!out.has(child)) {
        out.add(child);
        queue.push(child);
      }
    }
  }
  return out;
}

/**
 * "Move to…" for a wiki page (RADD-1009): pick a new parent from the SAME
 * space — the page itself and everything under it are excluded up front, so
 * the server's cycle guard is the backstop rather than the UX — or "Top
 * level" to make it a root. Sends `parent_id` alone: a move touches no
 * content, so there is no version to guard (the tree rows carry none).
 */
export function MovePageModal({
  page,
  rows,
  onClose,
}: {
  page: MoveRow;
  rows: MoveRow[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  // undefined = nothing chosen yet; null = top level.
  const [target, setTarget] = useState<string | null | undefined>(undefined);
  const excluded = useMemo(() => subtreeIds(rows, page.id), [rows, page.id]);
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows]);

  const needle = filter.trim().toLowerCase();
  const candidates = useMemo(
    () =>
      rows
        .filter((row) => !excluded.has(row.id))
        .filter((row) => !needle || row.title.toLowerCase().includes(needle))
        .sort(comparePagesNaturally),
    [rows, excluded, needle],
  );
  const visible = candidates.slice(0, MAX_VISIBLE);

  const move = useMutation({
    mutationFn: (parent_id: string | null) =>
      api.patch<Page>(apiPagePath(page.id), { parent_id } satisfies PageUpdate),
    onSuccess: async () => {
      await invalidateEntities(queryClient, Entity.page, Entity.docSpace);
      onClose();
    },
  });

  const chosen = target !== undefined;
  const unchanged = chosen && target === page.parent_id;
  const currentParent = page.parent_id ? byId.get(page.parent_id)?.title : null;

  const optionClass = (selected: boolean) =>
    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] cursor-pointer " +
    "focus-visible:outline-2 focus-visible:outline-focus " +
    (selected ? "bg-elevated text-heading" : "text-fg hover:bg-elevated/60");

  return (
    <Modal title={`Move “${page.title}”`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-fg-muted">
          {currentParent ? <>Currently under <span className="text-fg">{currentParent}</span>.</> : "Currently at the top level."}{" "}
          Its own pages move with it.
        </p>
        <ListSearchInput
          value={filter}
          onChange={setFilter}
          placeholder="Filter pages…"
          ariaLabel="Filter destination pages by title"
          total={rows.length - excluded.size}
          matched={candidates.length}
          noun="pages"
        />
        <div role="radiogroup" aria-label="New parent" className="max-h-72 overflow-y-auto rounded-lg border border-subtle p-1">
          <button
            type="button"
            role="radio"
            aria-checked={chosen && target === null}
            onClick={() => setTarget(null)}
            className={optionClass(chosen && target === null)}
          >
            <CornerLeftUp size={13} aria-hidden className="shrink-0 text-fg-faint" />
            <span className="flex-1">Top level</span>
            {page.parent_id === null && <span className="text-[11px] text-fg-faint">current</span>}
          </button>
          {visible.map((row) => (
            <button
              key={row.id}
              type="button"
              role="radio"
              aria-checked={target === row.id}
              onClick={() => setTarget(row.id)}
              className={optionClass(target === row.id)}
            >
              <span className="w-[13px] shrink-0">
                {target === row.id && <Check size={13} aria-hidden />}
              </span>
              <span className="min-w-0 flex-1 truncate">{row.title}</span>
              {row.id === page.parent_id && <span className="text-[11px] text-fg-faint">current</span>}
            </button>
          ))}
          {candidates.length > MAX_VISIBLE && (
            <p className="px-2 py-1.5 text-[11px] text-fg-faint">
              {candidates.length - MAX_VISIBLE} more — keep typing to narrow.
            </p>
          )}
          {candidates.length === 0 && needle && (
            <p className="px-2 py-1.5 text-xs text-fg-faint">No pages match “{filter.trim()}”.</p>
          )}
        </div>
        {move.isError && <ErrorText error={move.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => chosen && move.mutate(target)}
            disabled={!chosen || unchanged || move.isPending}
          >
            {move.isPending ? "Moving…" : "Move"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
