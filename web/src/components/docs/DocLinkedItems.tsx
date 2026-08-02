import { useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { RoutePath, apiDocPageItemPath, apiDocPageItemsPath } from "../../lib/constants";
import { CATEGORY_META } from "../../lib/meta";
import { docPageItemsQuery } from "../../lib/queries";
import type { DocLinkedItem, StateCategoryValue } from "../../lib/types";

/**
 * Linked-issues panel on a doc page (spec 43): key chip + title + state dot,
 * plus an add-by-key input (`TD-123`) when the caller may write docs.
 */
export function DocLinkedItems({ pageId, canWrite }: { pageId: string; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const items = useQuery(docPageItemsQuery(pageId));
  const [key, setKey] = useState("");

  const invalidate = () => void invalidateEntities(queryClient, Entity.docPage, Entity.item);
  const add = useMutation({
    mutationFn: (itemKey: string) =>
      api.post<DocLinkedItem>(apiDocPageItemsPath(pageId), { item_key: itemKey }),
    onSuccess: () => setKey(""),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (itemId: string) => api.delete<void>(apiDocPageItemPath(pageId, itemId)),
    onSettled: invalidate,
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = key.trim().toUpperCase();
    if (trimmed) add.mutate(trimmed);
  };

  if (items.isError) {
    return (
      <p className="text-xs text-red-400">Failed to load links: {errorMessage(items.error)}</p>
    );
  }

  const list = items.data ?? [];
  return (
    <div className="flex flex-col gap-2">
      {list.length === 0 ? (
        <p className="text-[13px] text-fg-faint">No linked issues yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {list.map((item) => (
            <li
              key={item.item_id}
              className="flex items-center gap-2 rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5"
            >
              <Link
                to={RoutePath.issue}
                params={{ itemKey: item.key }}
                className="flex min-w-0 flex-1 items-center gap-2 hover:underline"
              >
                <span className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary">
                  {item.key}
                </span>
                <span className="truncate text-[13px] text-fg">{item.title}</span>
              </Link>
              <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-fg-muted">
                <span
                  className={
                    "size-2 rounded-full " +
                    (CATEGORY_META[item.state_category as StateCategoryValue]?.dotClassName ??
                      "bg-fg-faint")
                  }
                  aria-hidden
                />
                {item.state}
              </span>
              {canWrite && (
                <button
                  type="button"
                  onClick={() => remove.mutate(item.item_id)}
                  disabled={remove.isPending}
                  aria-label={`Unlink ${item.key}`}
                  className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-50"
                >
                  <X size={13} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canWrite && (
        <form onSubmit={onSubmit} className="flex items-center gap-2">
          <input
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder="Link an issue by key (TD-123)"
            aria-label="Issue key"
            className="h-8 w-56 rounded-md border border-strong bg-surface px-2.5 font-mono text-xs text-heading placeholder:font-sans placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
          <button
            type="submit"
            disabled={add.isPending || !key.trim()}
            className="flex items-center gap-1.5 rounded border border-strong px-2 py-1 text-xs text-fg hover:bg-elevated cursor-pointer disabled:opacity-50"
          >
            <Plus size={12} aria-hidden />
            Link
          </button>
          {add.isError && <span className="text-xs text-red-400">{errorMessage(add.error)}</span>}
        </form>
      )}
    </div>
  );
}
