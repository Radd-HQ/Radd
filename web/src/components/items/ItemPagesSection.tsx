import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Plus, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import {
  PALETTE_SEARCH_LIMIT,
  RoutePath,
  SEARCH_DEBOUNCE_MS,
  apiPageItemPath,
  apiPageItemsPath,
} from "../../lib/constants";
import { useDebounced, usePermissions } from "../../lib/hooks";
import { pageSearchQuery, itemPagesQuery } from "../../lib/queries";
import { Permission, type PageLinkedItem, type Item } from "../../lib/types";

/**
 * Docs block INSIDE the Related links card (spec 43): pages pages linked to
 * this item, with unlink and a search-to-link picker (doc FTS) for doc
 * writers. Feature-detects the docs module by swallowing the list query error
 * — no pages module, no Pages block, and the card is web links only.
 */
export function ItemPagesSection({ item }: { item: Item }) {
  const perms = usePermissions();
  const canWrite = perms.global(Permission.pageWrite);
  const docs = useQuery(itemPagesQuery(item.id));

  if (docs.isError || docs.isPending) return null;
  const list = docs.data;
  if (list.length === 0 && !canWrite) return null;

  return (
    <section className="mt-3 border-t border-subtle pt-3">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">Pages</p>
      <div className="flex flex-col gap-2">
        {list.length === 0 ? (
          <p className="text-[13px] text-fg-faint">No linked docs yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {list.map((ref) => (
              <li
                key={ref.page_id}
                className="flex items-center gap-2 rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5"
              >
                <BookOpen size={14} className="shrink-0 text-fg-muted" aria-hidden />
                <Link
                  to={RoutePath.page}
                  params={{ spaceId: ref.space_id, pageId: ref.page_id }}
                  className="min-w-0 flex-1 truncate text-[13px] text-fg hover:underline"
                >
                  {ref.title}
                </Link>
                <span className="shrink-0 text-[11px] text-fg-faint">{ref.space_name}</span>
                {canWrite && <UnlinkButton pageId={ref.page_id} item={item} />}
              </li>
            ))}
          </ul>
        )}
        {canWrite && <LinkDocPicker item={item} />}
      </div>
    </section>
  );
}

function UnlinkButton({ pageId, item }: { pageId: string; item: Item }) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiPageItemPath(pageId, item.id)),
    onSettled: () => void invalidateEntities(queryClient, Entity.page),
  });
  return (
    <button
      type="button"
      onClick={() => remove.mutate()}
      disabled={remove.isPending}
      aria-label="Unlink doc"
      className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-50"
    >
      <X size={13} />
    </button>
  );
}

/** Search-as-you-type doc picker; choosing a hit links it to this issue. */
function LinkDocPicker({ item }: { item: Item }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, SEARCH_DEBOUNCE_MS);
  const results = useQuery(pageSearchQuery(debounced, PALETTE_SEARCH_LIMIT));

  const link = useMutation({
    mutationFn: (pageId: string) =>
      api.post<PageLinkedItem>(apiPageItemsPath(pageId), { item_key: item.key }),
    onSuccess: () => {
      setQuery("");
      setOpen(false);
    },
    onSettled: () => void invalidateEntities(queryClient, Entity.page),
  });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-fit items-center gap-1.5 rounded border border-strong px-2 py-1 text-xs text-fg hover:bg-elevated cursor-pointer"
      >
        <Plus size={12} aria-hidden />
        Link a page
      </button>
    );
  }

  const hits = results.data?.results ?? [];
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-subtle bg-surface/40 p-2.5">
      <div className="flex items-center gap-2">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search pages…"
          aria-label="Search pages"
          autoFocus
          className="h-8 flex-1 rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close doc picker"
          className="rounded p-1 text-fg-faint hover:text-fg cursor-pointer"
        >
          <X size={13} />
        </button>
      </div>
      {link.isError && <p className="text-xs text-red-400">{errorMessage(link.error)}</p>}
      {query.trim() !== "" && (
        <ul className="flex flex-col">
          {hits.map((hit) => (
            <li key={hit.page_id}>
              <button
                type="button"
                onClick={() => link.mutate(hit.page_id)}
                disabled={link.isPending}
                className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-[13px] text-fg hover:bg-elevated cursor-pointer disabled:opacity-50"
              >
                <BookOpen size={12} className="shrink-0 text-fg-faint" aria-hidden />
                <span className="truncate">{hit.title}</span>
              </button>
            </li>
          ))}
          {hits.length === 0 && !results.isFetching && (
            <li className="px-1.5 py-1 text-xs text-fg-faint">No matching docs.</li>
          )}
        </ul>
      )}
    </div>
  );
}
