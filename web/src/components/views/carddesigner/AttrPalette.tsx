import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { BucketDrop } from "../../../lib/bucket-drop";
import { CARD_EXCLUDED_BUILTINS, type CardLayout } from "../../../lib/card-layout";
import { columnCatalog, type ColumnDef } from "../../../lib/columns";
import type { FieldDef } from "../../../lib/types";
import type { DesignerDrag } from "./layout-ops";

/** Palette grouping — a scan order, not a taxonomy the model knows about. */
const GROUPS: { label: string; ids: string[] }[] = [
  { label: "Issue", ids: ["parent", "labels", "priority", "state", "points", "progress"] },
  { label: "People", ids: ["assignee", "reporter", "team"] },
  { label: "Dates", ids: ["start_date", "target_date", "created", "updated"] },
  { label: "Delivery", ids: ["cycle", "release", "sla", "logged_time"] },
];

/**
 * The card designer's attribute palette (spec 109): every placeable builtin +
 * the custom fields in the view's scope, drag-onto-the-preview (or click to
 * append). Placed attributes dim — one instance each.
 */
export function AttrPalette({
  fields,
  projectId,
  draft,
  drop,
  canEdit,
  onAdd,
}: {
  fields: FieldDef[];
  projectId: string | null;
  draft: CardLayout;
  drop: BucketDrop<DesignerDrag>;
  canEdit: boolean;
  /** Click fallback: append to the last row (or a new one). */
  onAdd: (attr: string) => void;
}) {
  const [search, setSearch] = useState("");
  const placed = useMemo(() => new Set(draft.cells.map((cell) => cell.attr)), [draft]);
  const catalog = useMemo(
    () => columnCatalog(fields, projectId).filter((c) => !CARD_EXCLUDED_BUILTINS.has(c.id)),
    [fields, projectId],
  );
  const byId = new Map(catalog.map((column) => [column.id, column]));
  const matches = (column: ColumnDef) =>
    column.label.toLowerCase().includes(search.toLowerCase());

  const chip = (column: ColumnDef) => {
    const isPlaced = placed.has(column.id);
    const draggable = canEdit && !isPlaced;
    return (
      <button
        key={column.id}
        type="button"
        draggable={draggable}
        disabled={!draggable}
        onDragStart={(event) => {
          event.dataTransfer.effectAllowed = "copy";
          drop.startDrag({ kind: "add", attr: column.id });
        }}
        onDragEnd={drop.endDrag}
        onClick={() => onAdd(column.id)}
        title={
          isPlaced
            ? "Already on the card"
            : `Drag onto the card (or click to append)${column.cf ? " — custom field" : ""}`
        }
        className={
          "rounded-md border px-2 py-0.5 text-left text-xs transition-colors " +
          (isPlaced
            ? "cursor-default border-subtle/60 text-fg-faint"
            : "cursor-grab border-strong text-fg-secondary hover:border-emphasis hover:text-fg")
        }
      >
        {column.label}
      </button>
    );
  };

  const customColumns = catalog.filter((column) => column.cf && matches(column));
  // Stale placed ids: on the card but no longer in any catalog group.
  const knownIds = new Set(catalog.map((column) => column.id));
  const staleIds = [...placed].filter((attr) => attr !== "title" && !knownIds.has(attr));

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
      <label className="flex items-center gap-1.5 rounded-md border border-subtle px-2 py-1">
        <Search size={12} className="shrink-0 text-fg-faint" aria-hidden />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Find an attribute…"
          className="w-full bg-transparent text-xs text-fg outline-none placeholder:text-fg-faint"
        />
      </label>
      {GROUPS.map((group) => {
        const columns = group.ids
          .map((id) => byId.get(id))
          .filter((column): column is ColumnDef => Boolean(column) && matches(column!));
        if (columns.length === 0) return null;
        return (
          <div key={group.label}>
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
              {group.label}
            </p>
            <div className="flex flex-wrap gap-1.5">{columns.map(chip)}</div>
          </div>
        );
      })}
      {customColumns.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
            Custom fields
          </p>
          <div className="flex flex-wrap gap-1.5">{customColumns.map(chip)}</div>
        </div>
      )}
      {staleIds.length > 0 && (
        <p className="text-[11px] text-amber-400">
          On the card but no longer in the field registry: {staleIds.join(", ")}. They render
          nothing — remove them from the preview.
        </p>
      )}
    </div>
  );
}
