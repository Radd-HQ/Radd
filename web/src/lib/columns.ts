import { useState } from "react";
import { viewColumnWidthsStorageKey } from "./constants";
import { fieldInScope } from "./field-scope";
import { FieldType, ViewType, type FieldDef } from "./types";

/**
 * List-view table columns (spec 108). The column SET (ids + order) lives on
 * the saved view (`view.columns` — shared, edit-gated, like group_by); WIDTHS
 * are per-user localStorage (ergonomics, swept by "Reset view"). A column id
 * is a builtin name below or `cf.<key>` for a custom field.
 */

export interface ColumnDef {
  id: string;
  label: string;
  /** Default width (px) until the user drags the header handle. */
  width: number;
  minWidth: number;
  /** Present on custom-field columns — drives the typed cell renderer. */
  cf?: FieldDef;
}

const COLUMN_MIN_WIDTH = 56;
const COLUMN_MAX_WIDTH = 480;
export const CUSTOM_COLUMN_PREFIX = "cf.";

/** The leading Item zone (selection/star/kind/flag/key/title) is itself a
 * fixed, resizable column (RADD-1110), stored under this pseudo id in the
 * widths map like any other — it is never a member of `view.columns`, so it
 * is not in the catalog and cannot be removed or reordered. */
export const TITLE_COLUMN_ID = "title";
const TITLE_MAX_WIDTH = 880;
export const TITLE_COLUMN: ColumnDef = {
  id: TITLE_COLUMN_ID,
  label: "Issue",
  width: 360,
  minWidth: 240,
};

/** The widest a column may be dragged or stored. */
export function columnMaxWidth(id: string): number {
  return id === TITLE_COLUMN_ID ? TITLE_MAX_WIDTH : COLUMN_MAX_WIDTH;
}

/** Clamp a stored/dragged width — stale values from older layouts (or wild
 * drags) must never blow the table out sideways. */
export function clampWidth(id: string, px: number): number {
  const min = id === TITLE_COLUMN_ID ? TITLE_COLUMN.minWidth : COLUMN_MIN_WIDTH;
  return Math.min(columnMaxWidth(id), Math.max(min, Math.round(px)));
}

/** A column's live width: the stored one, else its default. */
export function columnWidth(column: ColumnDef, widths: Record<string, number>): number {
  return widths[column.id] ?? column.width;
}

/** Builtin columns, in the picker's order. Ids reuse the CardSlot vocabulary
 * where a slot exists (type/labels/…/state) so defaults map 1:1. */
const BUILTIN_COLUMNS: ColumnDef[] = [
  { id: "type", label: "Issue type", width: 128, minWidth: COLUMN_MIN_WIDTH },
  { id: "parent", label: "Parent", width: 128, minWidth: COLUMN_MIN_WIDTH },
  { id: "labels", label: "Labels", width: 224, minWidth: 96 },
  { id: "cycle", label: "Cycle", width: 112, minWidth: COLUMN_MIN_WIDTH },
  { id: "release", label: "Release", width: 104, minWidth: COLUMN_MIN_WIDTH },
  { id: "start_date", label: "Start date", width: 96, minWidth: COLUMN_MIN_WIDTH },
  { id: "target_date", label: "Target date", width: 96, minWidth: COLUMN_MIN_WIDTH },
  { id: "team", label: "Team", width: 112, minWidth: COLUMN_MIN_WIDTH },
  { id: "priority", label: "Priority", width: 96, minWidth: COLUMN_MIN_WIDTH },
  { id: "visibility", label: "Visibility", width: 96, minWidth: COLUMN_MIN_WIDTH },
  { id: "assignee", label: "Assignee", width: 72, minWidth: COLUMN_MIN_WIDTH },
  { id: "reporter", label: "Reporter", width: 128, minWidth: COLUMN_MIN_WIDTH },
  { id: "sla", label: "SLA", width: 96, minWidth: COLUMN_MIN_WIDTH },
  { id: "points", label: "Points", width: 64, minWidth: COLUMN_MIN_WIDTH },
  { id: "progress", label: "Progress", width: 128, minWidth: 80 },
  { id: "logged_time", label: "Logged time", width: 88, minWidth: COLUMN_MIN_WIDTH },
  { id: "created", label: "Created", width: 96, minWidth: COLUMN_MIN_WIDTH },
  { id: "updated", label: "Updated", width: 96, minWidth: COLUMN_MIN_WIDTH },
  { id: "state", label: "State", width: 112, minWidth: COLUMN_MIN_WIDTH },
];

function customDefaultWidth(type: FieldDef["type"]): number {
  switch (type) {
    case FieldType.number:
    case FieldType.duration:
    case FieldType.boolean:
      return 88;
    case FieldType.date:
      return 96;
    case FieldType.select:
      return 112;
    case FieldType.user:
      return 128;
    case FieldType.multi_select:
      return 160;
    default: // text, url
      return 192;
  }
}

/** Every column the picker may offer for a view: builtins + the custom fields
 * in the view's scope (all-projects views get global fields only). */
export function columnCatalog(fields: FieldDef[], projectId: string | null): ColumnDef[] {
  const custom = fields
    .filter((field) => (projectId ? fieldInScope(field, projectId) : field.project_ids.length === 0))
    .map((field) => ({
      id: `${CUSTOM_COLUMN_PREFIX}${field.key}`,
      label: field.name,
      width: customDefaultWidth(field.type),
      minWidth: COLUMN_MIN_WIDTH,
      cf: field,
    }));
  return [...BUILTIN_COLUMNS, ...custom];
}

/** Stored ids -> defs, dropping ids the catalog no longer knows (a custom
 * field can leave the registry; the stored id stays until an editor removes
 * it, and the surface simply doesn't render it). */
export function resolveColumns(ids: readonly string[], catalog: ColumnDef[]): ColumnDef[] {
  const byId = new Map(catalog.map((column) => [column.id, column]));
  return ids.map((id) => byId.get(id)).filter((column): column is ColumnDef => Boolean(column));
}

/** Mirrors the pre-columns slot presets so existing views feel unchanged. */
const DEFAULT_LIST_COLUMNS: readonly string[] = [
  "type",
  "labels",
  "team",
  "priority",
  "assignee",
  "progress",
  "state",
];
const DEFAULT_PLANNING_COLUMNS: readonly string[] = ["priority", "assignee", "state"];
/** Queue rows kept their fixed reporter/SLA feel (spec 64) as defaults. */
const DEFAULT_QUEUE_COLUMNS: readonly string[] = [
  "type",
  "labels",
  "reporter",
  "priority",
  "assignee",
  "sla",
  "state",
];

export function defaultColumnsFor(viewType: string | undefined): readonly string[] {
  if (viewType === ViewType.queue) return DEFAULT_QUEUE_COLUMNS;
  if (viewType === ViewType.planning) return DEFAULT_PLANNING_COLUMNS;
  return DEFAULT_LIST_COLUMNS;
}

function readWidths(viewId: string | undefined): Record<string, number> {
  if (!viewId) return {};
  try {
    const raw = window.localStorage.getItem(viewColumnWidthsStorageKey(viewId));
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (typeof parsed !== "object" || parsed === null) return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>)
        .filter((entry): entry is [string, number] => typeof entry[1] === "number")
        .map(([id, px]) => [id, clampWidth(id, px)]),
    );
  } catch {
    return {};
  }
}

interface ColumnWidthsState {
  widths: Record<string, number>;
  /** Live update while dragging — state only. A boundary drag PATCHES both
   * neighbours atomically (two single-column writes would race each other). */
  applyWidths: (patch: Record<string, number>) => void;
  /** Release: state + localStorage. */
  commitWidths: (patch: Record<string, number>) => void;
  /** Back to every column's default (state + localStorage). */
  resetWidths: () => void;
}

/** Per-user column widths for one view (localStorage; live during drags). */
export function useColumnWidths(viewId: string | undefined): ColumnWidthsState {
  const [entry, setEntry] = useState(() => ({ key: viewId, widths: readWidths(viewId) }));
  // Re-seed on view navigation (same component instance, new view id).
  const widths = entry.key === viewId ? entry.widths : readWidths(viewId);
  if (entry.key !== viewId) setEntry({ key: viewId, widths });

  const clamped = (patch: Record<string, number>) =>
    Object.fromEntries(Object.entries(patch).map(([id, px]) => [id, clampWidth(id, px)]));
  const applyWidths = (patch: Record<string, number>) =>
    setEntry({ key: viewId, widths: { ...widths, ...clamped(patch) } });
  const commitWidths = (patch: Record<string, number>) => {
    const next = { ...widths, ...clamped(patch) };
    setEntry({ key: viewId, widths: next });
    if (viewId) {
      try {
        window.localStorage.setItem(viewColumnWidthsStorageKey(viewId), JSON.stringify(next));
      } catch {
        // Best-effort — the width still applies for the session.
      }
    }
  };
  const resetWidths = () => {
    setEntry({ key: viewId, widths: {} });
    if (viewId) {
      try {
        window.localStorage.removeItem(viewColumnWidthsStorageKey(viewId));
      } catch {
        // Best-effort.
      }
    }
  };
  return { widths, applyWidths, commitWidths, resetWidths };
}
