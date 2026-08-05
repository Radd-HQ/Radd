import { useState } from "react";
import { ArrowDown, ArrowUp, LayoutTemplate, SlidersHorizontal, X } from "lucide-react";
import {
  CARD_SLOT_LABELS,
  CARD_SLOT_ORDER,
  CardSlot,
  SCALE_MAX,
  SCALE_MIN,
  type CardDisplayState,
} from "../../lib/card-display";
import type { ColumnDef } from "../../lib/columns";
import { Button } from "../Button";
import { Popover } from "../Popover";
import { Select } from "../Select";

export const LABEL_CAP_OPTIONS = [1, 2, 3, 5, 99] as const;

/** Board views (spec 109): the card layout lives on the VIEW and is edited in
 * the full designer modal — this popover only opens it. */
export interface CardDesignerEntry {
  onOpen: () => void;
  canEdit: boolean;
}

/** Table-column editing for list surfaces (spec 108): the column SET is part
 * of the saved view (shared, view-edit gated); this popover edits it. */
export interface ColumnsEditor {
  /** Everything offerable: builtins + custom fields in the view's scope. */
  catalog: ColumnDef[];
  /** The view's current (or default) ordered column ids. */
  ids: string[];
  canEdit: boolean;
  onChange: (ids: string[]) => void;
  /** Clear the PERSONAL column widths too when resetting to defaults. */
  onResetWidths?: () => void;
}

/**
 * Toolbar "Display" popover — the widget builder for issue rows/cards. List
 * surfaces edit the view's COLUMNS (shared, spec 108); board views open the
 * card DESIGNER (the layout is on the view, spec 109); planning surfaces
 * still toggle chip SLOTS (personal, localStorage). Label cap rides the
 * layout for boards, this popover for the rest; surface zoom is always here.
 */
export function DisplayMenu({
  state,
  columnsEditor,
  cardDesigner,
}: {
  state: CardDisplayState;
  columnsEditor?: ColumnsEditor;
  cardDesigner?: CardDesignerEntry;
}) {
  const [open, setOpen] = useState(false);
  const { display, update, toggleSlot, reset } = state;
  const labelsVisible = cardDesigner
    ? false // the designer owns max_labels on boards
    : columnsEditor
      ? columnsEditor.ids.includes("labels")
      : display.slots.includes(CardSlot.labels);

  return (
    <div className="relative">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <SlidersHorizontal size={12} aria-hidden />
        Display
      </Button>

      <Popover
        open={open}
        onClose={() => setOpen(false)}
        label="Card display options"
        className="w-60 p-3"
      >
            {cardDesigner ? (
              <div>
                <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
                  Card layout
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  className="w-full justify-center"
                  onClick={() => {
                    setOpen(false);
                    cardDesigner.onOpen();
                  }}
                >
                  <LayoutTemplate size={13} aria-hidden />
                  {cardDesigner.canEdit ? "Design card…" : "View card layout…"}
                </Button>
                <p className="mt-2 text-[11px] text-fg-faint">
                  The card layout is part of this view — everyone sees it.
                  {cardDesigner.canEdit ? "" : " Only view editors change it."}
                </p>
              </div>
            ) : columnsEditor ? (
              <ColumnsSection editor={columnsEditor} />
            ) : (
              <>
                <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
                  Fields on items
                </p>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {CARD_SLOT_ORDER.map((slot) => (
                    <label
                      key={slot}
                      className="flex cursor-pointer items-center gap-1.5 text-xs text-fg"
                    >
                      <input
                        type="checkbox"
                        checked={display.slots.includes(slot)}
                        onChange={() => toggleSlot(slot)}
                        className="size-3.5 accent-accent"
                      />
                      {CARD_SLOT_LABELS[slot]}
                    </label>
                  ))}
                </div>
              </>
            )}

            {labelsVisible && (
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="text-xs text-fg-secondary">Labels shown</span>
                <Select
                  aria-label="Labels shown before +N"
                  value={String(display.maxLabels)}
                  onChange={(cap) => update({ maxLabels: Number(cap) })}
                  size="sm"
                  options={LABEL_CAP_OPTIONS.map((cap) => ({
                    value: String(cap),
                    label: cap === 99 ? "All" : String(cap),
                  }))}
                />
              </div>
            )}

            <div className="mt-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-fg-secondary">Scale</span>
                <span className="text-[11px] tabular-nums text-fg-muted">
                  {Math.round(display.scale * 100)}%
                </span>
              </div>
              <input
                type="range"
                aria-label="Surface scale"
                min={SCALE_MIN}
                max={SCALE_MAX}
                step={0.05}
                value={display.scale}
                onChange={(event) => update({ scale: Number(event.target.value) })}
                className="mt-1 w-full accent-accent"
              />
            </div>

            <Button
              variant="secondary"
              size="sm"
              className="mt-3 w-full justify-center"
              onClick={() => {
                reset();
                columnsEditor?.onResetWidths?.();
              }}
            >
              Reset to defaults
            </Button>
      </Popover>
    </div>
  );
}

/** The view's ordered column list: reorder/remove rows + an add select over
 * the catalog. Shared state — read-only without view-edit. */
function ColumnsSection({ editor }: { editor: ColumnsEditor }) {
  const { catalog, ids, canEdit, onChange } = editor;
  const byId = new Map(catalog.map((column) => [column.id, column]));
  const available = catalog.filter((column) => !ids.includes(column.id));

  const move = (index: number, delta: -1 | 1) => {
    const next = [...ids];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <div>
      <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
        Columns
      </p>
      <ul className="flex flex-col gap-1">
        {ids.map((id, index) => (
          <li key={id} className="flex items-center gap-1 text-xs text-fg">
            <span className="min-w-0 flex-1 truncate">
              {byId.get(id)?.label ?? (
                <span className="text-amber-400" title="No longer in the field registry">
                  {id}
                </span>
              )}
            </span>
            {canEdit && (
              <>
                <button
                  type="button"
                  onClick={() => move(index, -1)}
                  disabled={index === 0}
                  aria-label={`Move ${byId.get(id)?.label ?? id} up`}
                  className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer"
                >
                  <ArrowUp size={12} />
                </button>
                <button
                  type="button"
                  onClick={() => move(index, 1)}
                  disabled={index === ids.length - 1}
                  aria-label={`Move ${byId.get(id)?.label ?? id} down`}
                  className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer"
                >
                  <ArrowDown size={12} />
                </button>
                <button
                  type="button"
                  onClick={() => onChange(ids.filter((entry) => entry !== id))}
                  aria-label={`Remove the ${byId.get(id)?.label ?? id} column`}
                  className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
                >
                  <X size={12} />
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      {canEdit ? (
        <>
          {available.length > 0 && (
            <div className="mt-2">
              <Select
                aria-label="Add a column"
                value=""
                onChange={(picked) => {
                  if (picked) onChange([...ids, picked]);
                }}
                size="sm"
                options={[
                  { value: "", label: "Add a column…" },
                  ...available.map((column) => ({
                    value: column.id,
                    label: column.cf ? `${column.label} (custom)` : column.label,
                  })),
                ]}
              />
            </div>
          )}
          <p className="mt-2 text-[11px] text-fg-faint">
            Columns are part of this view — everyone sees this set. Drag the header edges to
            size them for yourself.
          </p>
        </>
      ) : (
        <p className="mt-2 text-[11px] text-fg-faint">
          Columns are part of this view — only view editors change them. Widths are yours:
          drag the header edges.
        </p>
      )}
    </div>
  );
}
