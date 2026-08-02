import { Fragment, useMemo } from "react";
import { AlignEndHorizontal, AlignStartHorizontal, X } from "lucide-react";
import type { BucketDrop } from "../../../lib/bucket-drop";
import {
  CARD_GRID_COLS,
  CARD_HEADER_ROW,
  CARD_TITLE_ATTR,
  lanesOf,
  type CardLayout,
  type CardLayoutCell,
} from "../../../lib/card-layout";
import { startHorizontalDrag } from "../../../lib/drag";
import type { FieldDef } from "../../../lib/types";
import { cellStyle, laneMargin } from "../../board/BoardCard";
import { renderCardCell, type CardCellCtx } from "../../board/card-cells";
import { FlagBadge, ItemKeyLink, KindBadge, StarBadge, TypeChip } from "../../items/ItemBadges";
import { dropKey, type DesignerDrag, type DropTarget } from "./layout-ops";
import { SAMPLE_ITEM, SAMPLE_ROLLUP, SAMPLE_SLA, SAMPLE_TIMELOG, sampleCustomValue } from "./sample-item";

/** ~296px card content (w-80 minus p-3) → one grid column's pixel width, for
 * translating a span-handle drag into columns. */
const COL_PX = 296 / CARD_GRID_COLS;

export interface PreviewProps {
  draft: CardLayout;
  cfByKey: Map<string, FieldDef>;
  drop: BucketDrop<DesignerDrag>;
  canEdit: boolean;
  selected: string | null;
  onSelect: (attr: string | null) => void;
  onDrop: (drag: DesignerDrag, target: DropTarget) => void;
  onRemove: (attr: string) => void;
  onResize: (attr: string, span: number) => void;
  onToggleAlign: (attr: string) => void;
}

type DropWiring = {
  drop: BucketDrop<DesignerDrag>;
  onDrop: (drag: DesignerDrag, target: DropTarget) => void;
};

/** Absolute overlay of 8 column drop zones over one lane (drag-time only). */
function ColumnZones({ row, drop, onDrop }: { row: number } & DropWiring) {
  return (
    <div className="absolute inset-0 z-10 flex">
      {Array.from({ length: CARD_GRID_COLS }, (_, col) => {
        const target: DropTarget = { row, col };
        const key = dropKey(target);
        return (
          <div
            key={col}
            {...drop.targetProps(key, (dragged) => onDrop(dragged, target))}
            className={
              "h-full flex-1 border-l border-dashed border-subtle/50 first:border-l-0 " +
              (drop.isOver(key) ? "bg-accent/25" : "")
            }
          />
        );
      })}
    </div>
  );
}

/** A slim between-lanes band that inserts a NEW row (drag-time only). */
function InsertRowBand({ afterRow, drop, onDrop }: { afterRow: number } & DropWiring) {
  const target: DropTarget = { newRowAfter: afterRow };
  const key = dropKey(target);
  return (
    <div
      {...drop.targetProps(key, (dragged) => onDrop(dragged, target))}
      className={
        "my-0.5 h-2 rounded transition-colors " +
        (drop.isOver(key) ? "bg-accent/40" : "bg-elevated/60")
      }
      title="New row"
    />
  );
}

/** Designer shell around one rendered cell: click-select, drag-to-move,
 * remove ✕, right-edge span handle. The INNER node is the real chip. */
function DesignerCell({
  cell,
  node,
  canEdit,
  isSelected,
  onSelect,
  onRemove,
  onResize,
  startDrag,
  endDrag,
}: {
  cell: CardLayoutCell;
  node: React.ReactNode;
  canEdit: boolean;
  isSelected: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onResize: (span: number) => void;
  startDrag: (drag: DesignerDrag) => void;
  endDrag: () => void;
}) {
  const isTitle = cell.attr === CARD_TITLE_ATTR;
  return (
    <span
      draggable={canEdit}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        startDrag({ kind: "move", attr: cell.attr });
      }}
      onDragEnd={endDrag}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
      style={cellStyle(cell)}
      className={
        "group/cell relative flex min-w-0 items-center rounded outline-offset-1 " +
        (cell.align === "end" ? "ml-auto " : "") +
        (canEdit ? "cursor-grab " : "") +
        (isSelected ? "outline-2 outline-focus" : "hover:outline-1 hover:outline-strong")
      }
    >
      {node}
      {canEdit && !isTitle && (
        <button
          type="button"
          aria-label={`Remove ${cell.attr}`}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="absolute -right-1.5 -top-1.5 z-20 hidden size-3.5 cursor-pointer items-center justify-center rounded-full bg-elevated text-fg-muted shadow-lift hover:text-red-400 group-hover/cell:flex"
        >
          <X size={9} aria-hidden />
        </button>
      )}
      {canEdit && (
        <span
          role="separator"
          aria-orientation="vertical"
          title="Drag to change the span"
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => {
            event.stopPropagation();
            startHorizontalDrag(event, {
              start: cell.span * COL_PX,
              min: COL_PX,
              max: CARD_GRID_COLS * COL_PX,
              onMove: () => {},
              onEnd: (px) => onResize(Math.round(px / COL_PX)),
            });
          }}
          className="absolute -right-0.5 bottom-0 top-0 z-10 hidden w-1 cursor-col-resize rounded bg-accent/50 group-hover/cell:block"
        />
      )}
    </span>
  );
}

/**
 * The live sample card (spec 109): the REAL lane renderer + cell registry over
 * a fully-populated stand-in item, each cell wrapped in designer chrome.
 * During a drag, per-lane column zones + insert-row bands overlay the card.
 */
export function CardPreview({
  draft,
  cfByKey,
  drop,
  canEdit,
  selected,
  onSelect,
  onDrop,
  onRemove,
  onResize,
  onToggleAlign,
}: PreviewProps) {
  // Synthesize a value for every placed custom field so cells never look dead.
  const sampleItem = useMemo(() => {
    const custom_fields: Record<string, ReturnType<typeof sampleCustomValue>> = {};
    for (const field of cfByKey.values()) custom_fields[field.key] = sampleCustomValue(field);
    return { ...SAMPLE_ITEM, custom_fields };
  }, [cfByKey]);

  const ctx: CardCellCtx = {
    item: sampleItem,
    sla: SAMPLE_SLA,
    rollup: SAMPLE_ROLLUP,
    timelog: SAMPLE_TIMELOG,
    maxLabels: draft.max_labels,
    usersById: new Map([["sample-assignee", "Alex Vega"]]),
    cfByKey,
    durations: { hoursPerDay: 8, daysPerWeek: 5 },
  };
  const lanes = lanesOf(draft);
  const headerLane = lanes.find((lane) => lane.row === CARD_HEADER_ROW);
  const bodyLanes = lanes.filter((lane) => lane.row !== CARD_HEADER_ROW);
  const dragActive = drop.dragging !== null;
  const lastRow = lanes.length > 0 ? lanes[lanes.length - 1].row : 0;

  const designerCell = (cell: CardLayoutCell) => (
    <DesignerCell
      key={cell.attr}
      cell={cell}
      node={renderCardCell(cell.attr, ctx) ?? <EmptyCellTag attr={cell.attr} />}
      canEdit={canEdit}
      isSelected={selected === cell.attr}
      onSelect={() => onSelect(selected === cell.attr ? null : cell.attr)}
      onRemove={() => onRemove(cell.attr)}
      onResize={(span) => onResize(cell.attr, span)}
      startDrag={drop.startDrag}
      endDrag={drop.endDrag}
    />
  );

  return (
    <div onClick={() => onSelect(null)}>
      <div className="w-80 rounded-xl border border-subtle bg-elevated p-3 shadow-lift">
        {/* Fixed chrome + the header lane (row 0). */}
        <div className="relative">
          <div className="flex items-center gap-1.5">
            {sampleItem.type ? (
              <TypeChip type={sampleItem.type} />
            ) : (
              <KindBadge kind={sampleItem.kind} size={13} />
            )}
            <span className="pointer-events-none">
              <ItemKeyLink itemKey={sampleItem.key} />
            </span>
            {(headerLane?.cells ?? [])
              .filter((cell) => cell.align !== "end")
              .map(designerCell)}
            <span className="ml-auto flex items-center gap-1.5">
              <StarBadge size={12} />
              <FlagBadge size={12} />
              {(headerLane?.cells ?? [])
                .filter((cell) => cell.align === "end")
                .map(designerCell)}
            </span>
          </div>
          {dragActive && <ColumnZones row={CARD_HEADER_ROW} drop={drop} onDrop={onDrop} />}
        </div>
        {dragActive && <InsertRowBand afterRow={CARD_HEADER_ROW} drop={drop} onDrop={onDrop} />}

        {bodyLanes.map((lane, index) => (
          <Fragment key={lane.row}>
            <div className="relative">
              <div className={`${laneMargin(index)} flex min-h-5 flex-wrap items-center gap-1.5`}>
                {lane.cells.map(designerCell)}
              </div>
              {dragActive && <ColumnZones row={lane.row} drop={drop} onDrop={onDrop} />}
            </div>
            {dragActive && <InsertRowBand afterRow={lane.row} drop={drop} onDrop={onDrop} />}
          </Fragment>
        ))}
        {dragActive && lastRow === CARD_HEADER_ROW && (
          <InsertRowBand afterRow={0} drop={drop} onDrop={onDrop} />
        )}
      </div>

      {/* Keyboard-and-click fallback toolbar for the selected cell. */}
      {selected && canEdit && (
        <SelectedCellHint
          attr={selected}
          align={draft.cells.find((cell) => cell.attr === selected)?.align ?? "start"}
          onToggleAlign={() => onToggleAlign(selected)}
          onRemove={selected === CARD_TITLE_ATTR ? undefined : () => onRemove(selected)}
        />
      )}
    </div>
  );
}

/** A placed attr whose sample value is empty (shouldn't happen — the sample
 * item is fully populated) still needs a visible, draggable body. */
function EmptyCellTag({ attr }: { attr: string }) {
  return (
    <span className="rounded border border-dashed border-strong px-1.5 py-px text-[10px] text-fg-faint">
      {attr}
    </span>
  );
}

function SelectedCellHint({
  attr,
  align,
  onToggleAlign,
  onRemove,
}: {
  attr: string;
  align: "start" | "end";
  onToggleAlign: () => void;
  onRemove?: () => void;
}) {
  return (
    <div className="mt-2 flex items-center gap-2 text-[11px] text-fg-muted">
      <span className="font-mono">{attr}</span>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onToggleAlign();
        }}
        title={align === "end" ? "Packed right — click to pack left" : "Packed left — click to pack right"}
        className="flex cursor-pointer items-center gap-1 rounded border border-subtle px-1.5 py-0.5 hover:border-strong hover:text-fg"
      >
        {align === "end" ? (
          <AlignEndHorizontal size={11} aria-hidden />
        ) : (
          <AlignStartHorizontal size={11} aria-hidden />
        )}
        {align === "end" ? "Right" : "Left"}
      </button>
      {onRemove && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="cursor-pointer rounded border border-subtle px-1.5 py-0.5 hover:border-strong hover:text-red-400"
        >
          Remove
        </button>
      )}
      <span className="text-fg-faint">Arrow keys move · +/− resize</span>
    </div>
  );
}
