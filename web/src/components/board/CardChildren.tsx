import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { usePeek } from "../../lib/hooks";
import { CATEGORY_META } from "../../lib/meta";
import { childItemsQuery } from "../../lib/queries";
import { compareChildrenOpenFirst } from "../../lib/view-utils";
import { Spinner } from "../Spinner";

/**
 * A board card's children, listed in place (RADD-698).
 *
 * The count chip was a dead end: it told you there were five subtasks and made
 * you open the parent to learn what they were. Expanding answers that where the
 * question is asked, and a click opens the child in PEEK — so inspecting a
 * subtask never costs you the board.
 *
 * Deliberately NOT the issue page's `ChildRow`: that row carries a tick box, an
 * assignee and a per-project states query, which on a 200-card board would be
 * 200 idle queries. What the two surfaces share is the ORDERING RULE (open work
 * first — `compareChildrenOpenFirst`), which is the part that would actually
 * drift if it were written twice.
 *
 * Children are fetched only once expanded: a listed item carries `child_count`,
 * not its children.
 */
export function CardChildren({ parentId }: { parentId: string }) {
  const { open: openPeek } = usePeek();
  const children = useQuery(childItemsQuery(parentId));
  const sorted = useMemo(
    () => [...(children.data ?? [])].sort(compareChildrenOpenFirst),
    [children.data],
  );

  return (
    // The card's own onClick opens the parent in peek; nothing in here should.
    <div
      className="mt-2 border-t border-subtle/60 pt-1.5"
      onClick={(event) => event.stopPropagation()}
      role="presentation"
    >
      {children.isPending ? (
        <Spinner label="Loading children…" />
      ) : children.isError ? (
        <p className="text-[11px] text-red-400">{errorMessage(children.error)}</p>
      ) : sorted.length === 0 ? (
        <p className="text-[11px] text-fg-faint">No children.</p>
      ) : (
        <ul className="flex flex-col">
          {sorted.map((child) => {
            const meta = CATEGORY_META[child.state.category];
            const finished = meta.order >= CATEGORY_META.done.order;
            return (
              <li key={child.id}>
                <button
                  type="button"
                  onClick={() => openPeek(child.key)}
                  title={`${child.key} · ${child.state.name}`}
                  className="flex w-full min-w-0 cursor-pointer items-center gap-1.5 rounded py-0.5 text-left hover:bg-surface/60 focus-visible:outline-2 focus-visible:outline-focus"
                >
                  <span
                    aria-hidden
                    className={`size-1.5 shrink-0 rounded-full ${meta.dotClassName}`}
                  />
                  <span className="shrink-0 font-mono text-[10px] text-fg-faint">{child.key}</span>
                  <span
                    className={`truncate text-[11px] ${
                      finished ? "text-fg-muted line-through" : "text-fg-secondary"
                    }`}
                  >
                    {child.title}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
