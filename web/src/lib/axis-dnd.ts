import {
  CF_AXIS_PREFIX,
  ItemKind,
  ViewAxis,
  type Cycle,
  type Item,
  type ItemParentRef,
  type ItemKindValue,
  type ItemUpdate,
  type PriorityValue,
  type State,
} from "./types";
import { BACKLOG_KEY, NO_EPIC_KEY, NO_TEAM_KEY, NO_VALUE_KEY, UNASSIGNED_KEY } from "./view-utils";

/**
 * Cross-bucket drag-and-drop (spec 24): dropping an item on a bucket sets the
 * field that the grouping axis represents — backlog → cycle sets `cycle_id`,
 * medium → high sets `priority`, etc. Pure planners here map (item, axis,
 * target bucket) to the server PATCH + an optimistic item merge; the view page
 * owns the mutation, the components own the DOM drag wiring.
 */

/** Everything a move planner needs to resolve a target bucket to concrete values. */
export interface AxisDndContext {
  /** True when the view is project-scoped — state buckets are then keyed by id.
   *  All-projects state buckets are keyed by NAME and resolve per item:
   *  `states` must then span every project in the view (allStatesQuery). */
  projectScoped: boolean;
  states?: State[];
  cycles?: Cycle[];
}

/** The minimum bucket shape a planner reads (id-or-sentinel key + display label). */
export interface BucketRef {
  key: string;
  label: string;
  /** Epic-axis lanes carry the epic itself, so an epic drop builds its
   *  optimistic ref from data rather than from the display label. */
  epicRef?: ItemParentRef;
}

/**
 * Which axes support cross-bucket drag. `kind` is create-only (no conversion
 * endpoint). Everything else — state, priority, assignee, team, cycle, and
 * select custom fields — is a plain PATCH; all-projects state drops
 * resolve the name-keyed bucket in the dragged item's OWN project (see
 * bucketMovePlan — an item whose project lacks that state stays put).
 */
export function dragEnabledForAxis(axis: string | null | undefined): boolean {
  if (!axis) return false;
  if (axis.startsWith(CF_AXIS_PREFIX)) return true;
  switch (axis) {
    case ViewAxis.state:
    case ViewAxis.stateCategory:
    case ViewAxis.priority:
    case ViewAxis.assignee:
    case ViewAxis.team:
    case ViewAxis.cycle:
    case ViewAxis.epic: // re-parents; the planner refuses illegal hierarchy moves
      return true;
    default: // kind, or anything unknown
      return false;
  }
}

export interface MovePlan {
  patch: ItemUpdate;
  /** Partial Item merged into the cache for the optimistic re-bucket. */
  optimistic: Partial<Item>;
}

/**
 * Plan the move of `item` into `bucket` along `axis`, or null if it is a no-op
 * (already in that bucket) or the axis/target can't resolve.
 */
export function bucketMovePlan(
  item: Item,
  axis: string,
  bucket: BucketRef,
  ctx: AxisDndContext,
): MovePlan | null {
  if (axis.startsWith(CF_AXIS_PREFIX)) {
    const fieldKey = axis.slice(CF_AXIS_PREFIX.length);
    const value = bucket.key === NO_VALUE_KEY ? null : bucket.key;
    if ((item.custom_fields[fieldKey] ?? null) === value) return null;
    return {
      patch: { custom_fields: { [fieldKey]: value } },
      optimistic: { custom_fields: { ...item.custom_fields, [fieldKey]: value } },
    };
  }
  switch (axis) {
    case ViewAxis.state: {
      // Project scope: buckets keyed by state id. All-projects scope: keyed by
      // NAME — resolve in the dragged item's own project (null = no such state
      // there; the caller can surface that).
      const state = ctx.projectScoped
        ? (ctx.states ?? []).find((s) => s.id === bucket.key)
        : (ctx.states ?? []).find(
            (s) => s.project_id === item.project_id && s.name === bucket.key,
          );
      if (!state || item.state.id === state.id) return null;
      return {
        patch: { state_id: state.id },
        optimistic: { state: { id: state.id, name: state.name, category: state.category } },
      };
    }
    case ViewAxis.stateCategory: {
      // RADD-851 → 854: a category drop transitions to the item's OWN
      // project's first state (by position) classified under that vocabulary
      // ROW — the same own-project resolution the all-projects state axis
      // does. A project with no state in the row keeps the item put. Bucket
      // keys are row keys; the six builtin keys coincide with the semantic
      // values, so the fallback buckets resolve identically.
      const current = (ctx.states ?? []).find((s) => s.id === item.state.id);
      if (current?.category_key === bucket.key) return null;
      const target = (ctx.states ?? [])
        .filter((s) => s.project_id === item.project_id && s.category_key === bucket.key)
        .sort((a, b) => a.position - b.position)[0];
      if (!target || item.state.id === target.id) return null;
      return {
        patch: { state_id: target.id },
        optimistic: { state: { id: target.id, name: target.name, category: target.category } },
      };
    }
    case ViewAxis.priority: {
      const priority = bucket.key as PriorityValue;
      if (item.priority === priority) return null;
      return { patch: { priority }, optimistic: { priority } };
    }
    case ViewAxis.assignee: {
      const id = bucket.key === UNASSIGNED_KEY ? null : bucket.key;
      if ((item.assignee?.id ?? null) === id) return null;
      return {
        patch: { assignee_id: id },
        optimistic: { assignee: id ? { id, name: bucket.label } : null },
      };
    }
    case ViewAxis.team: {
      const id = bucket.key === NO_TEAM_KEY ? null : bucket.key;
      if ((item.team?.id ?? null) === id) return null;
      return {
        patch: { team_id: id },
        optimistic: { team: id ? { id, name: bucket.label } : null },
      };
    }
    case ViewAxis.cycle: {
      const id = bucket.key === BACKLOG_KEY ? null : bucket.key;
      if ((item.cycle?.id ?? null) === id) return null;
      const cycle = id ? (ctx.cycles ?? []).find((c) => c.id === id) : null;
      return {
        patch: { cycle_id: id },
        optimistic: {
          cycle: cycle ? { id: cycle.id, name: cycle.name, status: cycle.status } : null,
        },
      };
    }
    case ViewAxis.epic: {
      // Dropping on an epic lane RE-PARENTS (RADD-697). The hierarchy is
      // epic <- issue <- subtask, so only an ISSUE may take an epic as its
      // parent: an epic has no parent at all, and a subtask's parent is its
      // issue — re-homing it to an epic would be a silent demotion of its
      // issue. Both are refused here rather than by a 409 the user must read.
      if (item.kind !== ItemKind.issue) return null;
      const ref = bucket.key === NO_EPIC_KEY ? null : (bucket.epicRef ?? null);
      if ((item.epic?.id ?? null) === (ref?.id ?? null)) return null;
      // An issue's epic IS its parent (one hop), so the patch is parent_id and
      // the optimistic merge updates both refs — they are the same row.
      return {
        patch: { parent_id: ref?.id ?? null },
        optimistic: { parent: ref, epic: ref },
      };
    }
    default:
      return null;
  }
}

/** Field prefill for the New Item modal, seeded from a bucket. */
export interface BucketCreatePreset {
  kind?: ItemKindValue;
  state_id?: string;
  priority?: PriorityValue;
  assignee_id?: string;
  team_id?: string;
  cycle_id?: string;
}

/**
 * Prefill for creating an item INTO a bucket (board quick-add): the same
 * axis→field mapping as `bucketMovePlan`, minus an existing item. Sentinel
 * buckets (Unassigned, No team, Backlog, …) preset nothing — the modal's own
 * defaults stand. Quick-add is only offered on project-scoped views, so state
 * buckets are keyed by id here; and unlike drag, the KIND axis works (kind is
 * create-only). Select custom-field axes preset nothing for now.
 */
export function bucketCreatePreset(axis: string, bucket: BucketRef): BucketCreatePreset {
  switch (axis) {
    case ViewAxis.state:
      return { state_id: bucket.key };
    case ViewAxis.priority:
      return { priority: bucket.key as PriorityValue };
    case ViewAxis.kind:
      return { kind: bucket.key as ItemKindValue };
    case ViewAxis.assignee:
      return bucket.key === UNASSIGNED_KEY ? {} : { assignee_id: bucket.key };
    case ViewAxis.team:
      return bucket.key === NO_TEAM_KEY ? {} : { team_id: bucket.key };
    case ViewAxis.cycle:
      return bucket.key === BACKLOG_KEY ? {} : { cycle_id: bucket.key };
    default:
      return {};
  }
}
