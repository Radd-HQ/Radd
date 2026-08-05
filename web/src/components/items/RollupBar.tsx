import { useQuery } from "@tanstack/react-query";
import { rollupBatchQuery } from "../../lib/queries";
import type { ItemRollup, RollupResponse } from "../../lib/types";
import { formatPoints } from "./ItemBadges";

/**
 * Epic progress (spec 76) — the board/list "progress" card slot (a slim
 * done/total bar on epic-kind items), fed by the batched POST /items/rollup.
 */

/** "3/8 done · 5 pts of 13" — the shared tooltip/summary line. */
export function rollupSummary(rollup: ItemRollup, showPoints: boolean): string {
  const parts = [`${rollup.done}/${rollup.total} done`];
  if (showPoints && rollup.points_total > 0) {
    parts.push(`${formatPoints(rollup.points_done)} pts of ${formatPoints(rollup.points_total)}`);
  }
  return parts.join(" · ");
}

function Bar({ rollup, className }: { rollup: ItemRollup; className: string }) {
  const done = rollup.total > 0 ? rollup.done / rollup.total : 0;
  const active = rollup.total > 0 ? rollup.in_progress / rollup.total : 0;
  return (
    <span className={`inline-flex overflow-hidden rounded-full bg-elevated ${className}`} aria-hidden>
      <span className="h-full bg-emerald-500/80" style={{ width: `${Math.round(done * 100)}%` }} />
      <span className="h-full bg-accent/60" style={{ width: `${Math.round(active * 100)}%` }} />
    </span>
  );
}

/** The slim card/row slot bar — renders nothing until the batch answers or
 * when the item has no descendants (a childless epic shows no empty chrome). */
export function RollupRowBar({
  rollup,
  showPoints = false,
}: {
  rollup: ItemRollup | undefined;
  showPoints?: boolean;
}) {
  if (!rollup || rollup.total === 0) return null;
  return (
    <span
      title={rollupSummary(rollup, showPoints)}
      className="inline-flex shrink-0 items-center gap-1"
    >
      <Bar rollup={rollup} className="h-1 w-14" />
      <span className="text-[10px] tabular-nums text-fg-muted">
        {rollup.done}/{rollup.total}
      </span>
    </span>
  );
}

/**
 * One rollup batch per loaded page (spec 76): keyed on the epic-kind item ids
 * on the surface. `enabled=false` (slot off / no epics visible) fetches
 * nothing and returns undefined — mirrors useSlaBatch. `staleTimeMs` lets big
 * surfaces (the roadmap's epic tints) refetch rarely; default is the
 * query-client default (fresh on mount/focus).
 */
export function useRollupBatch(
  itemIds: string[],
  enabled: boolean,
  staleTimeMs?: number,
): RollupResponse | undefined {
  const query = useQuery({
    ...rollupBatchQuery(itemIds),
    enabled: enabled && itemIds.length > 0,
    staleTime: staleTimeMs,
  });
  return enabled ? query.data : undefined;
}
