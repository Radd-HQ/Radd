/** One roadmap bar row: the label cell (sibling drag-to-reorder handle, spec 82)
 *  plus the positioned bar with its ghost chip, resize zones, ○ link handle,
 *  progress tint, and depends chip. Props in, JSX out — extracted from
 *  RoadmapTimeline.tsx verbatim. */

import type { DragEvent as ReactDragEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  Ban,
  BookmarkCheck,
  BookmarkPlus,
  ChevronDown,
  ChevronRight,
  Focus,
} from "lucide-react";
import { shortDate } from "../../lib/dates";
import { usePeek } from "../../lib/hooks";
import { CATEGORY_CHART_COLORS } from "../../lib/meta";
import { ItemLinkType, StateCategory } from "../../lib/types";
import { AssigneeAvatar, ItemKeyLink, KindBadge, PriorityIcon } from "../items/ItemBadges";
import {
  DragEdge,
  ROADMAP_BAR_INFO_MIN_PX,
  ROADMAP_LINK_HANDLE_HIT_PX,
  ROADMAP_ROW_H,
  RoadmapRowKind,
  barHitZones,
  barRenderWidth,
  isoFromDay,
  roadmapBarHeight,
  type BarProgress,
  type RoadmapRow,
  type RoadmapSpan,
} from "./roadmap-model";
import { BAR_ITEM_ATTR, BarDragMode, type BarDrag } from "./useBarDrag";


/** Categories whose solid fill is dark enough that on-bar text must go light.
    These are the terminal states, which share one slate by design (see the
    `--chart-*` block in index.css). */
const DARK_FILL_CATEGORIES: ReadonlySet<string> = new Set<string>([
  StateCategory.done,
  StateCategory.canceled,
]);

/** Depends-chip offset past the bar's CLAMPED right edge (read-only mode).
 *  In edit mode the gap instead clears the hover ○ link handle's hit box,
 *  which itself sits past any outside resize zone: outsidePx + handle +
 *  clearance. */
const BAR_TRAIL_GAP_PX = 6;
/** Extra clearance between the ○ handle's hit box and the depends chip. */
const BAR_TRAIL_HANDLE_CLEARANCE_PX = 2;
/** True if the cursor is in the top half of the event's target (row reorder,
 *  spec 82 — the ViewList idiom: top half = insert before). */
function isTopHalf(event: ReactDragEvent): boolean {
  const rect = event.currentTarget.getBoundingClientRect();
  return event.clientY < rect.top + rect.height / 2;
}
export function BarRow({
  row,
  innerWidth,
  dayWidth,
  labelWidth,
  canEdit,
  drag,
  domainStart,
  showConnectors,
  visibleIds,
  collapsed,
  containerDelta,
  progress,
  canReorder,
  reorderTarget,
  reorderIndicator,
  reordering,
  onRowDragStart,
  onRowDragEnd,
  onRowDragOver,
  onRowDrop,
  onToggleCollapse,
  soloed,
  onToggleSolo,
  isMember,
  onToggleMember,
  selected,
  onSelectRow,
  onContextMenu,
  onHoverStart,
  onHoverMove,
  onHoverEnd,
}: {
  row: RoadmapRow;
  innerWidth: number;
  dayWidth: number;
  /** LIVE label-gutter width — see the note on ROADMAP_LABEL_WIDTH. */
  labelWidth: number;
  canEdit: boolean;
  drag: BarDrag;
  domainStart: Date | null;
  showConnectors: boolean;
  visibleIds: ReadonlySet<string>;
  collapsed: boolean;
  /** Live snapped day delta of this row's PARENT EPIC mid-body-drag (spec 81):
   *  the child renders translated with the ghost treatment, null otherwise. */
  containerDelta: number | null;
  /** Progress-tint fraction for this bar (leaves: logged/estimate; epics:
   *  done/total children) — null = no overlay. */
  progress: BarProgress | null;
  /** Spec 82: the label cell is a drag-to-reorder handle (canEdit AND the
   *  view is rank-ordered). */
  canReorder: boolean;
  /** True while a SIBLING row's label drag is live — this label accepts the
   *  drop (top half = before, bottom half = after). */
  reorderTarget: boolean;
  /** Drop indicator while hovered: true = line above, false = below, null = none. */
  reorderIndicator: boolean | null;
  /** True while THIS row is mid bar-body reorder drag (spec 82 follow-up) —
   *  the row dims and its bar rings; the bar holds its x. */
  reordering: boolean;
  onRowDragStart: () => void;
  onRowDragEnd: () => void;
  onRowDragOver: (before: boolean) => void;
  onRowDrop: (before: boolean) => void;
  onToggleCollapse: (epicId: string) => void;
  /** This epic is in the solo set (epic rows only; focus-scheduling mode). */
  soloed: boolean;
  onToggleSolo: (epicId: string) => void;
  /** Curated membership (roadmap wave); null onToggleMember = no curate rights. */
  isMember: boolean;
  onToggleMember: ((itemId: string, makeMember: boolean) => void) | null;
  /** Selection (viewport wave): label click selects; F frames the selection. */
  selected: boolean;
  onSelectRow: (itemId: string, additive: boolean) => void;
  onContextMenu: (row: RoadmapRow, x: number, y: number) => void;
  /** Hover-card dwell wiring — the owner opens/suppresses/closes the card. */
  onHoverStart: (row: RoadmapRow, event: ReactPointerEvent) => void;
  onHoverMove: (row: RoadmapRow, event: ReactPointerEvent) => void;
  onHoverEnd: () => void;
}) {
  const { open: openPeek } = usePeek();
  const { item, rowKind } = row;
  const isEpic = rowKind === RoadmapRowKind.epic;
  const isChild = rowKind === RoadmapRowKind.child;
  const draggable = canEdit && !row.derived;
  const barGestures = draggable ? drag.barProps(row) : {};

  // The container slides as one: a child of the mid-drag epic previews at the
  // epic ghost's delta exactly like the dragged bar itself.
  const containerSpan: RoadmapSpan | null =
    containerDelta !== null
      ? { startIndex: row.startIndex + containerDelta, endIndex: row.endIndex + containerDelta }
      : null;
  const preview = drag.previewSpan(row) ?? containerSpan;
  const span = preview ?? { startIndex: row.startIndex, endIndex: row.endIndex };
  const left = span.startIndex * dayWidth;
  // Rendered width IS the logical width (one-day minimum by construction),
  // floored at the absolute grab minimum — presentation only; the logical
  // span and every commit stay on the true day indices.
  const width = barRenderWidth(span.startIndex, span.endIndex, dayWidth);
  // Tiered hit layout: normal bars keep inside resize zones; narrow bars get
  // slim inside slices extended OUTSIDE; tiny (one-day) bars move the zones
  // fully outside so the whole bar stays clean body-move area.
  const zones = barHitZones(width);
  const color = CATEGORY_CHART_COLORS[item.state.category];
  const barHeight = roadmapBarHeight(isEpic);
  // In-bar info needs room; narrower bars rely on the hover card instead.
  const showInBarInfo = width >= ROADMAP_BAR_INFO_MIN_PX;
  // Leaf bars are SOLID category fills — dark text reads on the three ACTED-ON
  // categories (yellow/blue/green), but the terminal states are dark slate and
  // need light text; epic fills stay translucent, so light text too. The same
  // split picks the progress-tint band color: a black band on the light fills,
  // a white band on the dark ones.
  const darkFill = isEpic || DARK_FILL_CATEGORIES.has(item.state.category);
  // `text-black` is a fixed literal on purpose: a zinc tier would invert with
  // the theme, and these fills do not — a light bar would end up with
  // near-white text on the light theme.
  const barTextClass = darkFill ? "text-heading" : "text-black";
  const isLinkTarget = drag.state?.mode === BarDragMode.link && drag.state.targetId === item.id;
  const isLinkSource =
    drag.state?.mode === BarDragMode.link && drag.state.row.item.id === item.id;

  // Connector mode keeps chips only for edges whose source bar isn't visible.
  const dependsOn = (item.links?.incoming ?? []).filter(
    (link) =>
      link.link_type === ItemLinkType.blocks &&
      (!showConnectors || !visibleIds.has(link.item.id)),
  );

  const ChevronIcon = collapsed ? ChevronRight : ChevronDown;

  // Row-reorder drop indicator (spec 82) — the ViewList idiom: an inset line
  // across the WHOLE row on the half the drop would land.
  const indicatorClass =
    reorderIndicator === true
      ? " shadow-[inset_0_2px_0_0] shadow-accent-hover"
      : reorderIndicator === false
        ? " shadow-[inset_0_-2px_0_0] shadow-accent-hover"
        : "";

  return (
    <div
      className={
        "group flex border-b border-subtle/40 hover:bg-surface/40" +
        indicatorClass +
        // Bar-body reorder (spec 82 follow-up): the dragged row dims while
        // the pointer hunts for a sibling half.
        (reordering ? " opacity-60" : "") +
        (selected ? " bg-accent/10" : "")
      }
      onContextMenu={
        canEdit
          ? (event) => {
              event.preventDefault();
              onHoverEnd();
              onContextMenu(row, event.clientX, event.clientY);
            }
          : undefined
      }
    >
      {/* Label cell = the spec-82 reorder handle: HTML5-draggable among
          SIBLINGS. dragOver/drop only engage while a sibling's drag is live
          (`reorderTarget`), and stopPropagation keeps the body's tray-drop
          machinery out of it; tray drags never set `rowDrag`, so the two
          HTML5 drags can't cross wires. */}
      <div
        draggable={canReorder}
        onDragStart={
          canReorder
            ? (event) => {
                event.dataTransfer.effectAllowed = "move";
                onHoverEnd();
                onRowDragStart();
              }
            : undefined
        }
        onDragEnd={canReorder ? onRowDragEnd : undefined}
        onDragOver={
          reorderTarget
            ? (event) => {
                event.preventDefault();
                event.stopPropagation();
                event.dataTransfer.dropEffect = "move";
                onRowDragOver(isTopHalf(event));
              }
            : undefined
        }
        onDrop={
          reorderTarget
            ? (event) => {
                event.preventDefault();
                event.stopPropagation();
                onRowDrop(isTopHalf(event));
              }
            : undefined
        }
        title={
          canReorder
            ? isChild
              ? "Drag to reorder within this epic"
              : "Drag to reorder among top-level rows"
            : undefined
        }
        style={{ width: labelWidth, height: ROADMAP_ROW_H }}
        // Sticky: the labels are the timeline's y-axis — they ride horizontal
        // scroll (opaque bg, above bars + connectors) so a row never loses its
        // identity. Sticky is paint-only, so the pointer↔day math (layout
        // coords) is untouched. A plain click SELECTS the row (ctrl/meta
        // toggles into the set; buttons/links inside keep their own verbs).
        onClick={(event) => {
          const target = event.target as HTMLElement;
          if (target.closest("button, a")) return;
          onSelectRow(item.id, event.ctrlKey || event.metaKey || event.shiftKey);
        }}
        className={`sticky left-0 z-30 flex shrink-0 items-center gap-1.5 border-r border-subtle pr-3 ${
          selected
            ? "border-l-2 border-l-accent bg-elevated"
            : "bg-surface group-hover:bg-elevated"
        } ${isChild ? "pl-8" : "pl-2"}${
          canReorder ? " cursor-grab active:cursor-grabbing" : ""
        }`}
      >
        {isEpic && row.scheduledChildCount > 0 ? (
          <button
            type="button"
            onClick={() => onToggleCollapse(item.id)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand children" : "Collapse children"}
            className="shrink-0 rounded p-px text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-focus cursor-pointer"
          >
            <ChevronIcon size={14} aria-hidden />
          </button>
        ) : (
          !isChild && <span className="w-4 shrink-0" aria-hidden />
        )}
        <KindBadge kind={item.kind} size={13} />
        <ItemKeyLink itemKey={item.key} />
        <span
          className={`min-w-0 flex-1 truncate text-[12px] ${
            isEpic ? "font-semibold text-heading" : "text-fg"
          }`}
          title={item.title}
        >
          {item.title}
        </span>
        {onToggleMember && rowKind !== RoadmapRowKind.child && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onToggleMember(item.id, !isMember);
            }}
            aria-pressed={isMember}
            aria-label={isMember ? "Remove from this roadmap" : "Add to this roadmap"}
            title={
              isMember
                ? "Pinned to this roadmap — click to remove"
                : "Pin to this roadmap (curated membership — the Members toggle shows only pinned items)"
            }
            className={`shrink-0 rounded p-px focus-visible:outline-2 focus-visible:outline-focus cursor-pointer ${
              isMember
                ? "text-accent-text"
                : "text-fg-faint opacity-0 hover:text-fg group-hover:opacity-100 focus-visible:opacity-100"
            }`}
          >
            {isMember ? (
              <BookmarkCheck size={13} aria-hidden />
            ) : (
              <BookmarkPlus size={13} aria-hidden />
            )}
          </button>
        )}
        {isEpic && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onToggleSolo(item.id);
            }}
            aria-pressed={soloed}
            aria-label={soloed ? "Unsolo this epic" : "Solo this epic"}
            title={
              soloed
                ? "Unsolo — bring the other rows back"
                : "Solo — show only this epic and its children (focus mode for scheduling one epic)"
            }
            className={`shrink-0 rounded p-px focus-visible:outline-2 focus-visible:outline-focus cursor-pointer ${
              soloed
                ? "text-accent-text"
                : "text-fg-faint opacity-0 hover:text-fg group-hover:opacity-100 focus-visible:opacity-100"
            }`}
          >
            <Focus size={13} aria-hidden />
          </button>
        )}
      </div>

      <div className="relative" style={{ width: innerWidth, height: ROADMAP_ROW_H }}>
        {/* Original position placeholder while the ghost is out. */}
        {preview && (
          <div
            className="absolute top-1/2 -translate-y-1/2 rounded-md bg-emphasis/25"
            style={{
              left: row.startIndex * dayWidth,
              width: barRenderWidth(row.startIndex, row.endIndex, dayWidth),
              height: barHeight,
            }}
            aria-hidden
          />
        )}

        <button
          type="button"
          {...{ [BAR_ITEM_ATTR]: item.id }}
          {...barGestures}
          onClick={() => {
            onHoverEnd();
            if (drag.consumeDragClick()) return;
            openPeek(item.key);
          }}
          onPointerEnter={(event) => onHoverStart(row, event)}
          // COMPOSE with the drag machinery's own move handler — an explicit
          // onPointerMove after the gesture spread REPLACES it (that killed
          // horizontal bar drags once; keep both firing).
          onPointerMove={(event) => {
            barGestures.onPointerMove?.(event);
            onHoverMove(row, event);
          }}
          onPointerLeave={onHoverEnd}
          aria-label={`${item.key} ${item.title}`}
          className={`absolute top-1/2 -translate-y-1/2 rounded-md focus-visible:outline-2 focus-visible:outline-focus ${
            draggable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"
          } ${preview || reordering ? "opacity-90 ring-1 ring-focus" : ""} ${
            isLinkTarget ? "ring-2 ring-focus" : ""
          }`}
          style={{
            left,
            width,
            height: barHeight,
            backgroundColor: isEpic ? `${color}33` : color,
            border: isEpic ? `1.5px ${row.derived ? "dashed" : "solid"} ${color}` : undefined,
            touchAction: draggable ? "none" : undefined,
          }}
        >
          {/* Progress tint: a left-anchored overlay band — logged/estimate on
              leaves, done/total children on epics. Black-tinted on the light
              category fills, white on the dark ones (epics, canceled), so it
              reads on both without fighting the category color. Overlogged
              leaves draw the full band plus a thin red right edge. */}
          {progress && progress.fraction > 0 && (
            <span
              className={`pointer-events-none absolute inset-y-0 left-0 rounded-l-md ${
                darkFill ? "bg-white/15" : "bg-base/25"
              } ${progress.fraction >= 1 ? "rounded-r-md" : ""}`}
              style={{ width: `${progress.fraction * 100}%` }}
              aria-hidden
            />
          )}
          {progress?.overlogged && (
            <span
              className="pointer-events-none absolute inset-y-0 right-0 w-0.5 rounded-r-md bg-red-500"
              aria-hidden
            />
          )}
          {/* In-bar info: truncated title + priority/assignee, only when the
              bar has room; pointer-events-none keeps every gesture (move,
              edge resize, link-drop targeting) on the bar itself. */}
          {showInBarInfo && (
            <span className="pointer-events-none flex h-full w-full min-w-0 items-center gap-1.5 overflow-hidden px-2">
              <span
                className={`min-w-0 flex-1 truncate text-left text-xs font-medium ${barTextClass}`}
              >
                {item.title}
              </span>
              <span
                className={`flex shrink-0 items-center gap-1 ${
                  isEpic ? "" : "rounded-full bg-base/25 px-1 py-0.5"
                }`}
              >
                <PriorityIcon priority={item.priority} size={14} />
                {item.assignee && <AssigneeAvatar assignee={item.assignee} />}
              </span>
            </span>
          )}
          {/* Edge resize zones — tiered by rendered width (barHitZones):
              normal = 6px inside; narrow = 4px inside + 6px OUTSIDE; tiny
              (one-day bars at any zoom) = fully outside, so even a 10px bar
              keeps its whole body as clean move area. The zones' own
              pointerdown handlers classify the gesture (begin() stops
              propagation), so hit layout and classification can never
              disagree. */}
          {draggable && (
            <>
              <span
                {...drag.edgeProps(row, DragEdge.start)}
                className="absolute inset-y-0 cursor-ew-resize"
                style={{
                  left: -zones.outsidePx,
                  width: zones.insidePx + zones.outsidePx,
                  touchAction: "none",
                }}
                aria-hidden
              />
              <span
                {...drag.edgeProps(row, DragEdge.end)}
                className="absolute inset-y-0 cursor-ew-resize"
                style={{
                  right: -zones.outsidePx,
                  width: zones.insidePx + zones.outsidePx,
                  touchAction: "none",
                }}
                aria-hidden
              />
            </>
          )}
        </button>

        {/* Ghost date chip: live start → target while dragging. Container-
            translated children skip it — one chip per gesture, on the epic. */}
        {preview && domainStart && containerDelta === null && (
          <span
            className="pointer-events-none absolute z-30 whitespace-nowrap rounded bg-elevated px-1.5 py-px text-[10px] font-medium text-fg shadow"
            style={{ left, top: -1 }}
          >
            {shortDate(isoFromDay(domainStart, span.startIndex))} →{" "}
            {shortDate(isoFromDay(domainStart, span.endIndex))}
          </span>
        )}

        {/* ○ link handle: drag to another bar to create a dependency link.
            The visible dot sits centered in an invisible 16px hit box that
            hangs off the CLAMPED right edge — past any outside resize zone,
            so it's always cleanly hoverable. */}
        {canEdit && (
          <span
            {...drag.linkProps(row)}
            title="Drag to another bar to link them — pick the type at drop (Blocks by default)"
            className="absolute top-1/2 flex -translate-y-1/2 cursor-crosshair items-center justify-center"
            style={{
              left: left + width + zones.outsidePx,
              width: ROADMAP_LINK_HANDLE_HIT_PX,
              height: ROADMAP_LINK_HANDLE_HIT_PX,
              touchAction: "none",
            }}
          >
            <span
              className={`size-2.5 rounded-full border-2 border-accent-hover bg-base transition-opacity ${
                isLinkSource ? "opacity-100" : "opacity-0 group-hover:opacity-100"
              }`}
              aria-hidden
            />
          </span>
        )}

        {/* Depends-on chip past the bar end — the fallback signal when the
            blocker's bar isn't on the surface (filtered out) or connectors
            are toggled off; the elbow lines + violation styling carry the
            signal otherwise. The old outside trailing TITLE is gone — the
            hover card replaces it — so the chip hangs alone off the clamped
            edge, past the ○ handle's hit box in edit mode. */}
        {dependsOn.length > 0 && (
          <span
            className="absolute top-1/2 flex -translate-y-1/2 items-center gap-0.5 whitespace-nowrap rounded bg-red-500/15 px-1 py-px text-[10px] font-medium text-red-300"
            title={`Depends on ${dependsOn.map((link) => link.item.key).join(", ")}`}
            style={{
              left:
                left +
                width +
                (canEdit
                  ? zones.outsidePx + ROADMAP_LINK_HANDLE_HIT_PX + BAR_TRAIL_HANDLE_CLEARANCE_PX
                  : BAR_TRAIL_GAP_PX),
            }}
          >
            <Ban size={10} aria-hidden />
            {dependsOn.map((link) => link.item.key).join(", ")}
          </span>
        )}
      </div>
    </div>
  );
}
