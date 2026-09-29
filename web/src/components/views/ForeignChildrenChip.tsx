import { Link } from "@tanstack/react-router";
import { RoutePath } from "../../lib/constants";
import type { ItemParentRef, ItemRollup } from "../../lib/types";
import { foreignChildren } from "../../lib/view-utils";

/**
 * RADD-1493: what a project-scoped surface does NOT show of an epic — its readable
 * descendants in other projects (a link to the epic's all-projects board) and the
 * ones the viewer may not read (a count). Renders nothing when there is nothing to
 * say, so a same-project epic's header is unchanged.
 */
export function ForeignChildrenChip({
  epicRef,
  rollup,
  projectKey,
}: {
  epicRef: ItemParentRef | undefined;
  rollup: ItemRollup | undefined;
  /** The surface's own project key; null on an all-projects surface (then nothing is foreign). */
  projectKey: string | null;
}) {
  if (!epicRef || projectKey === null) return null;
  const foreign = foreignChildren(rollup, projectKey);
  const withheld = rollup?.withheld ?? 0;
  if (foreign.count === 0 && withheld === 0) return null;
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 text-[11px] text-fg-muted"
      data-foreign-children={foreign.count}
      data-withheld={withheld}
    >
      {foreign.count > 0 && (
        <Link
          to={RoutePath.epicBoard}
          params={{ itemKey: epicRef.key }}
          title={`Open ${epicRef.key} as a board across every project`}
          className="rounded border border-subtle bg-elevated px-1.5 py-px text-fg-secondary hover:border-strong hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
        >
          {foreign.count} more in {foreign.keys.join(", ")}
        </Link>
      )}
      {withheld > 0 && <span title="Children in projects you cannot see">{withheld} you cannot see</span>}
    </span>
  );
}
