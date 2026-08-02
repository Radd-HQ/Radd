import { useLayoutEffect, useRef, useState } from "react";
import { shortDate } from "../../lib/dates";
import { formatDuration } from "../../lib/duration";
import { useDurationConfig } from "../../lib/hooks";
import { PRIORITY_META } from "../../lib/meta";
import type { ItemRollup, ItemTimelogBatchEntry } from "../../lib/types";
import { AssigneeAvatar, PriorityIcon, StatePill, TeamBadge } from "../items/ItemBadges";
import {
  RoadmapRowKind,
  epicBarProgress,
  leafBarProgress,
  type BarProgress,
  type RoadmapRow,
} from "./roadmap-model";

/**
 * Floating info card over a hovered roadmap bar (bar-presentation polish):
 * key + title, state/priority/assignee/team, the span dates, and — when the
 * data exists — the SAME progress fraction the bar tint draws (leaves:
 * logged/estimate off the timelog batch; epics: done/total children off the
 * rollup batch). One shared component for both bar kinds. Pointer-events-none
 * and purely presentational: the owner (RoadmapTimeline) opens it after a
 * hover dwell, suppresses it during any drag, and closes it on
 * leave/pointerdown/scroll. Replaces both the bars' old native `title`
 * tooltip and the outside trailing title label.
 */

const CARD_WIDTH_PX = 288;
/** Gap between the bar and the card. */
const CARD_GAP_PX = 8;
/** Minimum clearance the card keeps from every viewport edge. */
const CARD_VIEWPORT_MARGIN_PX = 8;

export interface RoadmapHoverCardProps {
  row: RoadmapRow;
  /** The hovered bar's viewport rect, captured when the dwell timer fired. */
  anchor: { left: number; top: number; bottom: number };
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

export function RoadmapHoverCard({ row, anchor, timelog, rollup }: RoadmapHoverCardProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const durationConfig = useDurationConfig();
  const { item } = row;
  const isEpic = row.rowKind === RoadmapRowKind.epic;
  const progress = isEpic ? epicBarProgress(rollup) : leafBarProgress(timelog);

  // Below the bar by default; flip above when the viewport bottom is near.
  // LinkPopover idiom: render at the raw anchor, correct pre-paint once the
  // card's real size is measurable.
  const [pos, setPos] = useState({ left: anchor.left, top: anchor.bottom + CARD_GAP_PX });
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    let top = anchor.bottom + CARD_GAP_PX;
    if (top + rect.height > window.innerHeight - CARD_VIEWPORT_MARGIN_PX) {
      top = anchor.top - rect.height - CARD_GAP_PX;
    }
    top = Math.max(
      CARD_VIEWPORT_MARGIN_PX,
      Math.min(top, window.innerHeight - rect.height - CARD_VIEWPORT_MARGIN_PX),
    );
    const left = Math.max(
      CARD_VIEWPORT_MARGIN_PX,
      Math.min(anchor.left, window.innerWidth - rect.width - CARD_VIEWPORT_MARGIN_PX),
    );
    setPos({ left, top });
  }, [anchor]);

  // Derived epics have no dates of their own — show the children union.
  const startIso = item.start_date ?? row.childrenBounds?.minStart ?? null;
  const targetIso = item.target_date ?? row.childrenBounds?.maxTarget ?? null;

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
              ? `${rollup.done} of ${rollup.total} children done`
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
