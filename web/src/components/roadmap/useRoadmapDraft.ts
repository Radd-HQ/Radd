/** The roadmap DRAFT buffer: every gesture pushes an OP here, the surface
 *  renders `applyTo(serverItems)`, and only Save replays the net result.
 *  Ops are COMPOUND, so undo/redo move in user-sized steps:
 *  - `patch`   — field changes (dates/flagged); an item not in the roadmap
 *                fetch (tray drop, a child a plan verb brings in) carries its
 *                full Item as an INSERT so it draws before Save;
 *  - `reorder` — one row's rank intent (anchor ids; the server ranks at save);
 *  - `chain`   — a sequential rank chain (date-order verb, auto-schedule);
 *  - `compound` — several of the above as ONE step (a plan's patches + its
 *                 rank chain), so Undo reverts the whole verb (RADD-1510).
 *  Derivation recomputes from base on every change, which keeps undo trivially
 *  correct. Link edits and membership pins stay immediate: both pass an
 *  explicit popover/menu step, so they are acts, not slips.
 */

import { useCallback, useMemo, useState } from "react";
import type { Item, ItemUpdate } from "../../lib/types";
import { DRAFT_FIELDS, applyOp, flattenOps, type DraftLeafOp, type DraftOp } from "./model/draft-ops";

export interface RoadmapDraft {
  dirty: boolean;
  /** Net changed-item count — the Save button's badge. */
  changedCount: number;
  canUndo: boolean;
  canRedo: boolean;
  /** Labels for the undo/redo tooltips ("Undo: Spread PX-1's children"). */
  undoLabel: string | null;
  redoLabel: string | null;
  applyTo: (items: Item[]) => Item[];
  pushOp: (op: DraftOp) => void;
  undo: () => void;
  redo: () => void;
  clear: () => void;
  /** Per-item NET field changes vs the base set (no-ops dropped) — the save
   *  batch. Inserted items diff against their own carried base values. */
  netPatches: (base: Item[]) => { itemId: string; patch: ItemUpdate }[];
  /** The rank intents, in op order — replayed sequentially at save. */
  intents: () => Extract<DraftLeafOp, { kind: "reorder" | "chain" }>[];
  /** The items the live ops carry as INSERTs (tray drops, children a plan
   *  brought in), first snapshot per id — the surface fetches these live so a
   *  link or title edit on a drafted row shows before Save (RADD-1506). */
  insertedItems: Item[];
}

export function useRoadmapDraft(): RoadmapDraft {
  const [ops, setOps] = useState<DraftOp[]>([]);
  const [redoOps, setRedoOps] = useState<DraftOp[]>([]);

  const pushOp = useCallback((op: DraftOp) => {
    setOps((previous) => [...previous, op]);
    setRedoOps([]);
  }, []);
  const undo = useCallback(() => {
    setOps((previous) => {
      if (previous.length === 0) return previous;
      const op = previous[previous.length - 1];
      setRedoOps((redo) => [...redo, op]);
      return previous.slice(0, -1);
    });
  }, []);
  const redo = useCallback(() => {
    setRedoOps((previous) => {
      if (previous.length === 0) return previous;
      const op = previous[previous.length - 1];
      setOps((applied) => [...applied, op]);
      return previous.slice(0, -1);
    });
  }, []);
  const clear = useCallback(() => {
    setOps([]);
    setRedoOps([]);
  }, []);

  const applyTo = useCallback(
    (items: Item[]) => ops.reduce((current, op) => applyOp(current, op), items),
    [ops],
  );

  const netPatches = useCallback(
    (base: Item[]) => {
      const baseline = new Map<string, Item>(base.map((item) => [item.id, item]));
      const merged = new Map<string, ItemUpdate>();
      for (const op of flattenOps(ops)) {
        if (op.kind !== "patch") continue;
        for (const patch of op.patches) {
          if (patch.insert && !baseline.has(patch.itemId)) {
            baseline.set(patch.itemId, patch.insert);
          }
          merged.set(patch.itemId, { ...merged.get(patch.itemId), ...patch.after });
        }
      }
      const out: { itemId: string; patch: ItemUpdate }[] = [];
      for (const [itemId, after] of merged) {
        const original = baseline.get(itemId);
        const patch: ItemUpdate = {};
        for (const field of DRAFT_FIELDS) {
          if (field in after && (!original || after[field] !== original[field])) {
            (patch as Record<string, unknown>)[field] = after[field];
          }
        }
        if (Object.keys(patch).length > 0) out.push({ itemId, patch });
      }
      return out;
    },
    [ops],
  );

  const intents = useCallback(
    () =>
      flattenOps(ops).filter(
        (op): op is Extract<DraftLeafOp, { kind: "reorder" | "chain" }> => op.kind !== "patch",
      ),
    [ops],
  );

  const insertedItems = useMemo(() => {
    const byId = new Map<string, Item>();
    for (const op of flattenOps(ops)) {
      if (op.kind !== "patch") continue;
      for (const patch of op.patches) {
        if (patch.insert && !byId.has(patch.itemId)) byId.set(patch.itemId, patch.insert);
      }
    }
    return [...byId.values()];
  }, [ops]);

  const changedCount = useMemo(() => {
    const touched = new Set<string>();
    for (const op of flattenOps(ops)) {
      if (op.kind === "patch") for (const patch of op.patches) touched.add(patch.itemId);
      else if (op.kind === "reorder") touched.add(op.itemId);
      else for (const id of op.orderedIds) touched.add(id);
    }
    return touched.size;
  }, [ops]);

  return {
    dirty: ops.length > 0,
    changedCount,
    canUndo: ops.length > 0,
    canRedo: redoOps.length > 0,
    undoLabel: ops.length > 0 ? ops[ops.length - 1].label : null,
    redoLabel: redoOps.length > 0 ? redoOps[redoOps.length - 1].label : null,
    applyTo,
    pushOp,
    undo,
    redo,
    clear,
    netPatches,
    intents,
    insertedItems,
  };
}
