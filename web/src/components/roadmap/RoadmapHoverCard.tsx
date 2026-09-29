import { useRef } from "react";
import { shortDate } from "@radd/plugin-sdk";
import { formatDuration } from "../../lib/duration";
import { useAnchoredCardPosition, type CardAnchor } from "../../lib/floating-position";
import { useDurationConfig } from "../../lib/hooks";
import { PRIORITY_META } from "../../lib/meta";
import type { Item, ItemRollup, ItemTimelogBatchEntry } from "../../lib/types";
import { foreignChildren, projectKeyOf } from "../../lib/view-utils";
import { AssigneeAvatar, PriorityIcon, StatePill, TeamBadge } from "../items/ItemBadges";
import { RoadmapRowKind, rowWindowIso, type BarProgress, type RoadmapRow } from "./roadmap-model";

/**
 * Floating info card over a hovered bar: key, title, state/priority/assignee/
 * team, span dates, and the SAME progress fraction the bar tint draws.
 * Pointer-events-none and purely presentational — RoadmapTimeline owns the
 * dwell, the drag suppression and closing.
 */

const CARD_WIDTH_PX = 288;

interface RoadmapHoverCardProps {
  row: RoadmapRow;
  /** Cursor-derived anchor box; the card sits below `bottom`, or above `top` near the viewport bottom. */
  anchor: CardAnchor;
  /** The row's progress (`rowBarProgress`) — null = no line/tint. */
  progress: BarProgress | null;
  /** This item's timelog batch entry (leaves) — undefined = no line/tint. */
  timelog: ItemTimelogBatchEntry | undefined;
  /** This item's rollup (epics) — undefined = no line/tint. */
  rollup: ItemRollup | undefined;
}

/** Slim progress track — emerald for epic done-fraction (the RollupBar
 *  convention), indigo for leaf logged-fraction; overlog caps it red. */
function ProgressTrack({ progress, isEpic }: { progress: BarProgress; isEpic: boolean }) {
  return (
    <span className="relative flex h-1 w-full overflow-hidden rounded-full bg-elevated" aria-hidden>
      <span
        className={`h-full rounded-full ${isEpic ? "bg-emerald-500/80" : "bg-accent/70"}`}
        style={{ width: `${progress.fraction * 100}%` }}
      />
      {progress.overlogged && <span className="absolute inset-y-0 right-0 w-1 bg-red-500" />}
    </span>
  );
}

export function RoadmapHoverCard({ row, anchor, progress, timelog, rollup }: RoadmapHoverCardProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const durationConfig = useDurationConfig();
  const { item } = row;
  const isEpic = row.rowKind === RoadmapRowKind.epic;
  const pos = useAnchoredCardPosition(rootRef, anchor);
  const { start: startIso, target: targetIso } = rowWindowIso(row);

  return (
    <div
      ref={rootRef}
      role="tooltip"
      style={{ left: pos.left, top: pos.top, width: CARD_WIDTH_PX }}
      className="pointer-events-none fixed z-50 rounded-lg border border-strong bg-surface p-3 shadow-xl shadow-black/40"
    >
      <p className="font-mono text-[11px] text-fg-muted">{item.key}</p>
      <p className="mt-0.5 line-clamp-2 text-[13px] font-medium leading-snug text-heading">
        {item.title}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <StatePill state={item.state} />
        <span className="inline-flex items-center gap-1 text-[11px] text-fg-secondary">
          <PriorityIcon priority={item.priority} size={13} />
          {PRIORITY_META[item.priority].label}
        </span>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fg-secondary">
        {item.assignee ? (
          <span className="inline-flex items-center gap-1">
            <AssigneeAvatar assignee={item.assignee} />
            {item.assignee.name}
          </span>
        ) : (
          <span className="text-fg-faint">Unassigned</span>
        )}
        {item.team && <TeamBadge team={item.team} />}
      </div>

      {startIso && targetIso && (
        <p className="mt-1.5 text-[11px] tabular-nums text-fg-secondary">
          {shortDate(startIso)} → {shortDate(targetIso)}
          {row.derived && <span className="text-fg-faint"> · from children</span>}
        </p>
      )}

      {progress && (
        <div className="mt-2 flex flex-col gap-1">
          <p className="text-[11px] tabular-nums text-fg-secondary">
            {isEpic && rollup
              ? `${rollup.done} of ${rollup.total} children done${elsewhereText(rollup, item)}`
              : timelog && (
                  <>
                    Estimate {formatDuration(timelog.estimate_seconds ?? 0, durationConfig)} ·
                    Logged {formatDuration(timelog.logged_seconds, durationConfig)}
                    {progress.overlogged && <span className="text-red-400"> · over</span>}
                  </>
                )}
          </p>
          <ProgressTrack progress={progress} isEpic={isEpic} />
        </div>
      )}
    </div>
  );
}

/** RADD-1493: " · 3 in TD, ITE · 2 you cannot see" — what this epic's bar does not draw. */
function elsewhereText(rollup: ItemRollup, item: Pick<Item, "key">): string {
  const foreign = foreignChildren(rollup, projectKeyOf(item));
  const parts: string[] = [];
  if (foreign.count > 0) parts.push(`${foreign.count} in ${foreign.keys.join(", ")}`);
  if (rollup.withheld > 0) parts.push(`${rollup.withheld} you cannot see`);
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}
