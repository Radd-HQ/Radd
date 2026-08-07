import { useEffect, useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { RoutePath, apiPageItemPath, apiPageItemsPath } from "../../lib/constants";
import { CATEGORY_META } from "../../lib/meta";
import { pageItemsQuery } from "../../lib/queries";
import type { PageLinkedItem, StateCategoryValue } from "../../lib/types";
import { Button } from "../Button";
import { IconButton } from "../IconButton";

/**
 * Linked-issues section on a page (spec 43): key chip + title + state dot, plus
 * an add-by-key input (`TD-123`) when the caller may write pages.
 *
 * **It owns its heading and it collapses** (RADD-943). Empty, this was a
 * heading, a "no linked issues yet", a 224px input and a button — ~90px of
 * chrome on every page in the wiki, most of which will never link an issue. It
 * opens when it has something to show and stays shut when it does not, which is
 * the same judgement `PageBacklinksPanel` makes by rendering nothing at all;
 * the difference is that this one has an action inside it, so it has to stay
 * reachable.
 *
 * Rows the page's TEXT produced carry no unlink button. Offering an X that
 * reappears on the next save would be a lie about who owns the link — the body
 * does, and the server refuses the delete for the same reason.
 */
export function PageLinkedItems({ pageId, canWrite }: { pageId: string; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const items = useQuery(pageItemsQuery(pageId));
  const [key, setKey] = useState("");
  const [open, setOpen] = useState(false);

  const list = items.data ?? [];
  // Open once the first links arrive, and only then — a reader who shut the
  // section keeps it shut, because `open` is only forced in one direction.
  useEffect(() => {
    if (list.length > 0) setOpen(true);
  }, [list.length]);

  const invalidate = () => void invalidateEntities(queryClient, Entity.page, Entity.item);
  const add = useMutation({
    mutationFn: (itemKey: string) =>
      api.post<PageLinkedItem>(apiPageItemsPath(pageId), { item_key: itemKey }),
    onSuccess: () => setKey(""),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (itemId: string) => api.delete<void>(apiPageItemPath(pageId, itemId)),
    onSettled: invalidate,
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = key.trim().toUpperCase();
    if (trimmed) add.mutate(trimmed);
  };

  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <section className="mt-8 border-t border-subtle pt-4">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted hover:text-fg cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <Chevron size={13} aria-hidden />
        Linked issues
        {list.length > 0 && (
          <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
            {list.length}
          </span>
        )}
      </button>

      {open && (
        <div className="mt-3 flex flex-col gap-2">
          {items.isError ? (
            <p className="text-xs text-red-400">
              Failed to load links: {errorMessage(items.error)}
            </p>
          ) : list.length === 0 ? (
            <p className="text-[13px] text-fg-faint">
              No linked issues yet — mentioning one in the page links it automatically.
            </p>
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
                  {item.derived ? (
                    <span
                      className="shrink-0 text-[11px] text-fg-faint"
                      title="Mentioned in this page — remove the mention to remove the link"
                    >
                      in the text
                    </span>
                  ) : (
                    canWrite && (
                      <IconButton
                        danger
                        onClick={() => remove.mutate(item.item_id)}
                        disabled={remove.isPending}
                        aria-label={`Unlink ${item.key}`}
                      >
                        <X size={13} />
                      </IconButton>
                    )
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
              <Button
                variant="secondary"
                size="sm"
                type="submit"
                disabled={add.isPending || !key.trim()}
              >
                <Plus size={12} aria-hidden />
                Link
              </Button>
              {add.isError && <span className="text-xs text-red-400">{errorMessage(add.error)}</span>}
            </form>
          )}
        </div>
      )}
    </section>
  );
}
