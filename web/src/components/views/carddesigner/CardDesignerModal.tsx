import { useEffect, useMemo, useState } from "react";
import { useBucketDrop } from "../../../lib/bucket-drop";
import {
  activeCardLayout,
  DEFAULT_BOARD_CARD_LAYOUT,
  isDefaultCardLayout,
  type CardLayout,
} from "../../../lib/card-layout";
import type { FieldDef, View } from "../../../lib/types";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { Select } from "../../Select";
import { LABEL_CAP_OPTIONS } from "../DisplayMenu";
import { AttrPalette } from "./AttrPalette";
import { CardPreview } from "./CardPreview";
import {
  nudgeCol,
  nudgeRow,
  placeCell,
  removeCell,
  resizeCell,
  toggleAlign,
  type DesignerDrag,
  type DropTarget,
} from "./layout-ops";
import { PresetPicker } from "./PresetPicker";

/**
 * The card designer (spec 109): a WYSIWYG editor for the view's board-card
 * layout. Palette on the left, the live sample card on the right — drag
 * attributes onto it, drag cells to move them, resize spans, toggle
 * alignment; arrow keys / +/− work on the selected cell. Save PATCHes the
 * view (`null` when the draft equals the default, so untouched views keep
 * tracking the evolving default card). The modal body never scrolls — HTML5
 * drag has no autoscroll — only the palette scrolls internally.
 */
export function CardDesignerModal({
  view,
  fields,
  canEdit,
  onSave,
  onClose,
}: {
  view: View;
  fields: FieldDef[];
  canEdit: boolean;
  onSave: (layout: CardLayout | null) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<CardLayout>(() => structuredClone(activeCardLayout(view)));
  const [selected, setSelected] = useState<string | null>(null);
  const drop = useBucketDrop<DesignerDrag>(canEdit);

  const cfByKey = useMemo(
    () =>
      new Map(
        fields
          .filter((field) =>
            view.project_id
              ? field.project_ids.length === 0 || field.project_ids.includes(view.project_id)
              : field.project_ids.length === 0,
          )
          .map((field) => [field.key, field]),
      ),
    [fields, view.project_id],
  );

  const apply = (next: CardLayout | null) => {
    if (next) setDraft(next);
  };
  const handleDrop = (drag: DesignerDrag, target: DropTarget) => apply(placeCell(draft, drag, target));
  const appendAttr = (attr: string) => {
    // Click fallback: into the last body row, or a new one when it's full.
    const lastRow = Math.max(0, ...draft.cells.map((cell) => cell.row));
    apply(
      placeCell(draft, { kind: "add", attr }, { row: lastRow, col: 7 }) ??
        placeCell(draft, { kind: "add", attr }, { newRowAfter: lastRow }),
    );
  };

  // Keyboard ops on the selected cell (the drag fallback).
  useEffect(() => {
    if (!selected || !canEdit) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      const current = draft.cells.find((cell) => cell.attr === selected);
      if (!current) return;
      const ops: Record<string, () => void> = {
        ArrowLeft: () => apply(nudgeCol(draft, selected, -1)),
        ArrowRight: () => apply(nudgeCol(draft, selected, 1)),
        ArrowUp: () => apply(nudgeRow(draft, selected, -1)),
        ArrowDown: () => apply(nudgeRow(draft, selected, 1)),
        "+": () => apply(resizeCell(draft, selected, current.span + 1)),
        "-": () => apply(resizeCell(draft, selected, current.span - 1)),
        Delete: () => apply(removeCell(draft, selected)),
        Backspace: () => apply(removeCell(draft, selected)),
      };
      const op = ops[event.key];
      if (op) {
        event.preventDefault();
        op();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, canEdit, draft]);

  const save = () => {
    onSave(isDefaultCardLayout(draft) ? null : draft);
    onClose();
  };

  return (
    <Modal title="Card designer" onClose={onClose} extraWide>
      <div className="flex gap-5">
        {/* Palette + presets: the only scrolling region. */}
        <div className="flex max-h-[60vh] w-56 shrink-0 flex-col gap-4">
          <AttrPalette
            fields={fields}
            projectId={view.project_id}
            draft={draft}
            drop={drop}
            canEdit={canEdit}
            onAdd={canEdit ? appendAttr : () => {}}
          />
          <PresetPicker draft={draft} canEdit={canEdit} onApply={(layout) => setDraft(layout)} />
        </div>

        <div className="min-w-0 flex-1">
          <p className="mb-2 text-[11px] text-fg-muted">
            {canEdit
              ? "Drag attributes onto the card; drag cells to move them. The top row sits beside the key; chips keep their natural width — the span handle mainly sizes title and labels."
              : "The card layout is part of this view — only view editors change it."}
          </p>
          <CardPreview
            draft={draft}
            cfByKey={cfByKey}
            drop={drop}
            canEdit={canEdit}
            selected={selected}
            onSelect={setSelected}
            onDrop={handleDrop}
            onRemove={(attr) => apply(removeCell(draft, attr))}
            onResize={(attr, span) => apply(resizeCell(draft, attr, span))}
            onToggleAlign={(attr) => apply(toggleAlign(draft, attr))}
          />
          <div className="mt-3 flex items-center justify-between gap-2">
            <label className="flex items-center gap-2 text-xs text-fg-secondary">
              Labels shown
              <Select
                aria-label="Labels shown before +N"
                value={String(draft.max_labels)}
                onChange={(cap) => canEdit && setDraft({ ...draft, max_labels: Number(cap) })}
                size="sm"
                options={LABEL_CAP_OPTIONS.map((cap) => ({
                  value: String(cap),
                  label: cap === 99 ? "All" : String(cap),
                }))}
              />
            </label>
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-subtle pt-3">
        <Button
          variant="ghost"
          size="sm"
          disabled={!canEdit}
          onClick={() => setDraft(structuredClone(DEFAULT_BOARD_CARD_LAYOUT))}
        >
          Reset to default
        </Button>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" disabled={!canEdit} onClick={save}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}
