/** The roadmap draft's PURE half (RADD-1151): op shapes and the fold that
 *  applies them to a base item set. Dependency-free on purpose so
 *  `web/scripts/roadmap-draft.test.mjs` can import it straight into node —
 *  the hook (`useRoadmapDraft`) owns state, undo/redo and the save diff. */

import type { Item, ItemUpdate } from "../../../lib/types";

export interface DraftFieldPatch {
  itemId: string;
  after: ItemUpdate;
  /** Tray-drop scheduling: the full item to draw when the base set lacks it. */
  insert?: Item;
}

export type DraftLeafOp =
  | { kind: "patch"; label: string; patches: DraftFieldPatch[] }
  | {
      kind: "reorder";
      label: string;
      itemId: string;
      afterId: string | null;
      beforeId: string | null;
    }
  | { kind: "chain"; label: string; orderedIds: string[] };

/** A `compound` op is ONE user-sized step made of several leaf ops (a plan's
 *  date patches plus the rank chain that orders its rows, RADD-1510), so a
 *  single Undo reverts the whole verb — RADD-1433 found auto-schedule
 *  recording two steps, with one Undo reverting only the ordering. */
export type DraftOp = DraftLeafOp | { kind: "compound"; label: string; ops: DraftLeafOp[] };

/** The draftable field subset (what roadmap gestures may change). */
export const DRAFT_FIELDS = ["start_date", "target_date", "flagged"] as const;

/** The leaf ops in order, compounds opened — the save diff, the rank intents
 *  and the changed-count badge all walk leaves. */
export function flattenOps(ops: readonly DraftOp[]): DraftLeafOp[] {
  return ops.flatMap((op) => (op.kind === "compound" ? op.ops : [op]));
}

export function applyOp(items: Item[], op: DraftOp): Item[] {
  switch (op.kind) {
    case "compound":
      return op.ops.reduce(applyOp, items);
    case "patch": {
      let next = items;
      for (const patch of op.patches) {
        const index = next.findIndex((item) => item.id === patch.itemId);
        if (index >= 0) {
          next = [...next];
          next[index] = { ...next[index], ...patch.after };
        } else if (patch.insert) {
          next = [...next, { ...patch.insert, ...patch.after }];
        }
      }
      return next;
    }
    case "reorder": {
      const from = items.findIndex((item) => item.id === op.itemId);
      if (from < 0) return items;
      const next = [...items];
      const [moved] = next.splice(from, 1);
      const anchor = op.beforeId ?? op.afterId;
      const at = next.findIndex((item) => item.id === anchor);
      if (at < 0) return items;
      next.splice(op.beforeId ? at : at + 1, 0, moved);
      return next;
    }
    case "chain": {
      // Reorder the subset to the given sequence at the first member's slot.
      const wanted = new Set(op.orderedIds);
      const first = items.findIndex((item) => item.id === op.orderedIds[0]);
      if (first < 0) return items;
      const byId = new Map(items.map((item) => [item.id, item]));
      const sequence = op.orderedIds
        .map((id) => byId.get(id))
        .filter((item): item is Item => Boolean(item));
      const rest = items.filter((item) => !wanted.has(item.id));
      const at = Math.min(first, rest.length);
      return [...rest.slice(0, at), ...sequence, ...rest.slice(at)];
    }
  }
}
