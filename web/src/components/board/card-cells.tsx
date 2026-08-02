import type { ReactNode } from "react";
import { ChevronRight, CornerDownRight } from "lucide-react";
import { CARD_TITLE_ATTR } from "../../lib/card-layout";
import { CUSTOM_COLUMN_PREFIX } from "../../lib/columns";
import { formatSeconds } from "../../lib/dates";
import type { formatDuration } from "../../lib/duration";
import { PRIORITY_META } from "../../lib/meta";
import {
  type FieldDef,
  type Item,
  type ItemParentRef,
  type ItemRollup,
  type ItemTimelogBatchEntry,
  type PriorityValue,
  type SlaBatchTimer,
} from "../../lib/types";
import { isOverdue } from "../items/CardSlots";
import { CustomCell, DateText, isEmptyCustomValue } from "../items/CustomFieldValue";
import {
  AssigneeAvatar,
  ChildCount,
  CycleChip,
  DueBadge,
  PointsChip,
  ReleaseChip,
  StatePill,
  TeamBadge,
  UnassignedSlot,
} from "../items/ItemBadges";
import { RollupRowBar } from "../items/RollupBar";
import { SlaRowChip } from "../items/SlaChips";

/**
 * Attribute-id → chip rendering for board-card cells (spec 109). One registry
 * shared by the real card (BoardCard), the swimlane variant and the designer's
 * live preview, so what you place is what renders. An EMPTY value returns
 * `null` — the cell simply doesn't exist on that card, and a lane whose cells
 * all return null collapses (the old `hasFooter` behavior).
 */

/** Priority as a compact mono tag (board cards): text reads faster than an
 * icon at card scale, and severity carries in the color. */
export function PriorityTag({ priority }: { priority: PriorityValue }) {
  const meta = PRIORITY_META[priority];
  return (
    <span
      title={`Priority: ${meta.label}`}
      className={`shrink-0 font-mono text-[10px] font-semibold uppercase tracking-wider ${meta.className}`}
    >
      {meta.short}
    </span>
  );
}

/** Parent epic as a pastel chip carrying the epic's NAME (its key in the
 * tooltip) — purple is the app's epic hue. Board-local: rows keep ParentTag. */
export function EpicChip({ parent }: { parent: ItemParentRef }) {
  return (
    <span
      title={`Parent: ${parent.key} ${parent.title}`}
      className="inline-flex min-w-0 max-w-40 items-center gap-1 rounded bg-purple-500/15 px-1.5 py-px text-[11px] leading-4 text-purple-300"
    >
      <CornerDownRight size={11} className="shrink-0" aria-hidden />
      <span className="truncate">{parent.title || parent.key}</span>
    </span>
  );
}

/** Quiet label chips for cards — labels are context, not signal, so they sit
 * a step back from the colored meta chips (board-local; rows keep LabelChips). */
export function QuietLabels({ labels, max }: { labels: string[]; max: number }) {
  const shown = max > 0 ? labels.slice(0, max) : [];
  const hidden = labels.slice(shown.length);
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1">
      {shown.map((label) => (
        <span
          key={label}
          className="inline-flex items-center rounded border border-subtle/70 bg-surface/70 px-1.5 py-px font-mono text-[10.5px] leading-4 text-fg-secondary"
        >
          {label}
        </span>
      ))}
      {hidden.length > 0 && (
        <span
          title={hidden.join(", ")}
          className="inline-flex shrink-0 items-center rounded border border-subtle/70 bg-surface/70 px-1.5 py-px font-mono text-[10.5px] leading-4 text-fg-muted"
        >
          +{hidden.length}
        </span>
      )}
    </span>
  );
}

export interface CardCellCtx {
  item: Item;
  /** Batch data — undefined while the attr isn't placed (the batch is gated). */
  sla?: SlaBatchTimer[];
  rollup?: ItemRollup;
  timelog?: ItemTimelogBatchEntry;
  maxLabels: number;
  /** Directory names for `user`-typed custom fields (fetched only while one
   * is placed) and field defs for `cf.<key>` attrs. */
  usersById?: Map<string, string>;
  cfByKey?: Map<string, FieldDef>;
  durations: Parameters<typeof formatDuration>[1];
  /** RADD-698: supplied by real boards to make the progress cell a DISCLOSURE
   *  (expand the card to list its children). Absent on the card designer's
   *  preview, which renders the same chip inert — a preview must not fetch. */
  childrenExpanded?: boolean;
  onToggleChildren?: () => void;
}

export function renderCardCell(attr: string, ctx: CardCellCtx): ReactNode {
  const { item } = ctx;
  if (attr.startsWith(CUSTOM_COLUMN_PREFIX)) {
    const field = ctx.cfByKey?.get(attr.slice(CUSTOM_COLUMN_PREFIX.length));
    if (!field) return null; // stale id — the field left the registry
    const value = item.custom_fields?.[field.key] ?? null;
    if (isEmptyCustomValue(value)) return null;
    return (
      <span title={field.name} className="flex min-w-0 items-center">
        <CustomCell
          type={field.type}
          value={value}
          usersById={ctx.usersById}
          durations={ctx.durations}
        />
      </span>
    );
  }
  switch (attr) {
    case CARD_TITLE_ATTR:
      // min-h reserves both clamped lines (uniform card heights).
      return (
        <p className="min-h-[2.75em] line-clamp-2 text-sm font-medium leading-snug text-heading">
          {item.title}
        </p>
      );
    case "parent":
      return item.parent ? <EpicChip parent={item.parent} /> : null;
    case "labels":
      return item.labels.length > 0 ? (
        <QuietLabels labels={item.labels} max={ctx.maxLabels} />
      ) : null;
    case "cycle":
      return item.cycle ? <CycleChip cycle={item.cycle} /> : null;
    case "release":
      return item.release ? <ReleaseChip release={item.release} /> : null;
    case "start_date":
      return item.start_date ? (
        <span title="Start date">
          <DateText iso={item.start_date} />
        </span>
      ) : null;
    case "target_date":
      return item.target_date ? (
        <DueBadge date={item.target_date} overdue={isOverdue(item)} />
      ) : null;
    case "team":
      return item.team ? <TeamBadge team={item.team} /> : null;
    case "priority":
      return <PriorityTag priority={item.priority} />;
    case "assignee":
      return item.assignee ? <AssigneeAvatar assignee={item.assignee} /> : <UnassignedSlot />;
    case "reporter":
      return item.reporter ? (
        <span
          title={`Reporter: ${item.reporter.name}`}
          className="flex min-w-0 items-center gap-1.5"
        >
          <AssigneeAvatar assignee={item.reporter} />
          <span className="truncate text-xs text-fg-secondary">{item.reporter.name}</span>
        </span>
      ) : null;
    case "sla":
      return ctx.sla && ctx.sla.length > 0 ? <SlaRowChip timers={ctx.sla} /> : null;
    case "points":
      return item.estimate_points != null ? <PointsChip points={item.estimate_points} /> : null;
    case "progress": {
      // Folds the old structural ChildCount in: the rollup bar once the batch
      // lands, the plain n-children count before/without it. RADD-698 dropped
      // the epic-only guard — an ISSUE's subtask progress is the same question
      // asked one level down, and the lane already reserved this row's height.
      const total = ctx.rollup?.total ?? item.child_count ?? 0;
      if (total <= 0) return null;
      const chip =
        ctx.rollup && ctx.rollup.total > 0 ? (
          <RollupRowBar rollup={ctx.rollup} />
        ) : (
          <ChildCount count={total} />
        );
      if (!ctx.onToggleChildren) return chip;
      return (
        <button
          type="button"
          // The card itself opens peek on click; this must not.
          onClick={(event) => {
            event.stopPropagation();
            ctx.onToggleChildren?.();
          }}
          aria-expanded={ctx.childrenExpanded ?? false}
          aria-label={`${ctx.childrenExpanded ? "Hide" : "Show"} children of ${item.key}`}
          title={ctx.childrenExpanded ? "Hide children" : "Show children"}
          className="flex cursor-pointer items-center gap-0.5 rounded hover:bg-surface/60 focus-visible:outline-2 focus-visible:outline-focus"
        >
          {chip}
          <ChevronRight
            size={11}
            aria-hidden
            className={`shrink-0 text-fg-faint transition-transform ${
              ctx.childrenExpanded ? "rotate-90" : ""
            }`}
          />
        </button>
      );
    }
    case "logged_time": {
      const seconds = ctx.timelog?.logged_seconds ?? 0;
      if (seconds <= 0) return null;
      return (
        <span
          title={
            ctx.timelog?.estimate_seconds != null
              ? `Logged ${formatSeconds(seconds)} of ${formatSeconds(ctx.timelog.estimate_seconds)} estimated`
              : `Logged ${formatSeconds(seconds)}`
          }
          className="font-mono text-[11px] tabular-nums text-fg-muted"
        >
          {formatSeconds(seconds)}
        </span>
      );
    }
    case "created":
      return (
        <span title="Created">
          <DateText iso={item.created_at} />
        </span>
      );
    case "updated":
      return (
        <span title="Updated">
          <DateText iso={item.updated_at} />
        </span>
      );
    case "state":
      return <StatePill state={item.state} />;
    default:
      return null; // unknown attr (a future id or plugin leftovers) — skip
  }
}
