import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import {
  ROADMAP_CASCADE_MAX_ITEMS,
  ROADMAP_EPIC_SPAN_DAYS,
  ROADMAP_LEAF_SPAN_DAYS,
  apiItemRankPath,
  roadmapCollapseStorageKey,
} from "../../lib/constants";
import {
  useAddItemLink,
  useRemoveItemLink,
  useReorderItem,
  useRoadmapItemPatch,
  type RoadmapDatePatch,
} from "../../lib/item-mutations";
import { pushToast } from "../../lib/toast";
import {
  ItemKind,
  type Item,
  type ItemUpdate,
  type View,
} from "../../lib/types";
import type { ConnectorEdge } from "./Connectors";
import {
  RANK_CHAIN_MIN_ITEMS,
  RoadmapRowKind,
  cascadePlan,
  cascadePlanMulti,
  childrenDateOrder,
  epicMovePlan,
  epicStretchPatches,
  isoDaysBetween,
  isoFromDay,
  roadmapReorderNeighbours,
  shiftIso,
  todayIso,
  type RoadmapModel,
  type RoadmapMove,
  type RoadmapPlanPatch,
  type RoadmapRow,
  type RoadmapSpan,
} from "./roadmap-model";
import { BarDragMode, type CommitModifiers } from "./useBarDrag";
import type { RoadmapDraft } from "./useRoadmapDraft";

/**
 * Everything stateful about roadmap EDITING (specs 77 + 78 + 79 + 82), so
 * RoadmapSurface stays chrome: the date-PATCH mutation (with the dependency
 * cascade + the union-deduped parent-epic auto-stretch), tray drop scheduling,
 * the link popover (create after a ○-drop, retype/remove from a connector
 * click), the per-VIEW epic collapse set (localStorage, spec 79 — roadmaps are
 * saved views), the context-menu anchor, and the spec-82 rank writes: the
 * sibling row reorder and the sequential rank chain (date-order verb +
 * auto-schedule's appended chain).
 */

export interface RoadmapMenuAnchor {
  row: RoadmapRow;
  x: number;
  y: number;
}

/** The link popover's subject: `linkId` present = editing an existing link. */
export interface RoadmapLinkAnchor {
  x: number;
  y: number;
  sourceId: string;
  sourceKey: string;
  targetId: string;
  targetKey: string;
  linkId?: string;
  linkType?: string;
}

const EMPTY_SET: ReadonlySet<string> = new Set();

function loadCollapsed(viewId: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(roadmapCollapseStorageKey(viewId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

export function useRoadmapEditing(
  view: Pick<View, "id" | "query_string">,
  model: RoadmapModel,
  /** The draft buffer (draft wave): gestures push ops here; Save replays. */
  draft: RoadmapDraft,
  /** The UN-drafted server items — the save diff's baseline. */
  baseItems: Item[],
) {
  const queryClient = useQueryClient();
  const patchItems = useRoadmapItemPatch(view);
  const reorderItem = useReorderItem(view);
  const [saving, setSaving] = useState(false);
  const addLink = useAddItemLink("");
  const removeLink = useRemoveItemLink("");
  const [menu, setMenu] = useState<RoadmapMenuAnchor | null>(null);
  const [linkAnchor, setLinkAnchor] = useState<RoadmapLinkAnchor | null>(null);

  // Collapse state is per VIEW (spec 79) — reloaded when the view changes.
  const viewId = view.id;
  const [collapsedIds, setCollapsedIds] = useState<ReadonlySet<string> | null>(null);
  useEffect(() => {
    setCollapsedIds(loadCollapsed(viewId));
  }, [viewId]);

  const toggleCollapse = useCallback(
    (epicId: string) => {
      setCollapsedIds((previous) => {
        const next = new Set(previous ?? []);
        if (next.has(epicId)) next.delete(epicId);
        else next.add(epicId);
        window.localStorage.setItem(roadmapCollapseStorageKey(viewId), JSON.stringify([...next]));
        return next;
      });
    },
    [viewId],
  );

  /** Replace the whole collapse set (toolbar Collapse-all/Expand-all; an
   *  empty iterable = everything expanded). Same per-view persistence. */
  const setAllCollapsed = useCallback(
    (epicIds: Iterable<string>) => {
      const next = new Set(epicIds);
      window.localStorage.setItem(roadmapCollapseStorageKey(viewId), JSON.stringify([...next]));
      setCollapsedIds(next);
    },
    [viewId],
  );

  /** Record a patch list as ONE draft op (menu verbs, plans) — nothing hits
   *  the server until Save (draft wave). `onSuccess` fires synchronously so
   *  the existing toast/chain call sites keep working unchanged. */
  const applyPatches = useCallback(
    (patches: RoadmapDatePatch[], onSuccess?: () => void, label?: string) => {
      if (patches.length === 0) return;
      draft.pushOp({
        kind: "patch",
        label:
          label ?? `Edit ${patches.length === 1 ? "1 item" : `${patches.length} items`}`,
        patches: patches.map((entry) => ({
          itemId: entry.itemId,
          after: entry.patch,
          insert: entry.insert,
        })),
      });
      onSuccess?.();
    },
    [draft],
  );

  /** Flush the draft: ONE batched field PATCH of the net changes, then the
   *  rank intents replayed in op order (anchors are ids, so date patches and
   *  reorders never interact). Clears the buffer on success. */
  const saveDraft = useCallback(async () => {
    if (!draft.dirty || saving) return;
    setSaving(true);
    try {
      const patches = draft
        .netPatches(baseItems)
        .map((entry) => ({ itemId: entry.itemId, patch: entry.patch, optimistic: { ...entry.patch } }));
      if (patches.length > 0) await patchItems.mutateAsync({ patches });
      for (const intent of draft.intents()) {
        if (intent.kind === "reorder") {
          await reorderItem.mutateAsync({
            itemId: intent.itemId,
            afterId: intent.afterId,
            beforeId: intent.beforeId,
          });
        } else {
          for (let index = 1; index < intent.orderedIds.length; index++) {
            await api.patch<Item>(apiItemRankPath(intent.orderedIds[index]), {
              after_id: intent.orderedIds[index - 1],
              before_id: null,
            });
          }
        }
      }
      draft.clear();
      pushToast("Roadmap changes saved");
    } catch (error) {
      pushToast(errorMessage(error));
    } finally {
      setSaving(false);
      void invalidateEntities(queryClient, Entity.item);
    }
  }, [draft, baseItems, saving, patchItems, reorderItem, queryClient]);

  /**
   * Commit a move/resize (specs 78 + 81): PATCH the changed date(s); when the
   * target date changed, run the dependency cascade over the loaded rows
   * (skipped with Alt held at drop, aborted past the cap) — every push joins
   * the SAME optimistic unit. A BODY move of a non-derived epic is a CONTAINER
   * move: every loaded scheduled child shifts by the same delta and the whole
   * moved set seeds the (multi-seed) cascade; Alt = "just this bar" skips the
   * children too. Union-deduped parent-epic outward stretches ride along for
   * every moved item; one rollback + toast on failure.
   */
  const commitSpan = useCallback(
    (row: RoadmapRow, span: RoadmapSpan, modifiers: CommitModifiers) => {
      if (!model.domainStart) return;
      const start = isoFromDay(model.domainStart, span.startIndex);
      const target = isoFromDay(model.domainStart, span.endIndex);
      const patches: RoadmapDatePatch[] = [];
      const append = (planned: RoadmapPlanPatch[]) => {
        for (const entry of planned) {
          patches.push({ itemId: entry.itemId, patch: entry.patch, optimistic: { ...entry.patch } });
        }
      };
      let onSuccess: (() => void) | undefined;

      // Epic container move (spec 81): the epic + its loaded scheduled
      // children shift together (RESIZE and Alt keep the single-bar path).
      const containerMove =
        modifiers.mode === BarDragMode.move &&
        !modifiers.alt &&
        row.rowKind === RoadmapRowKind.epic &&
        !row.derived;
      if (containerMove) {
        const deltaDays = isoDaysBetween(row.item.start_date!, start);
        const plan = epicMovePlan(model.rows, row.item.id, deltaDays);
        if (plan.patches.length === 0) return;
        append(plan.patches);
        const seeds: RoadmapMove[] = plan.patches.map((entry) => ({
          itemId: entry.itemId,
          start: entry.patch.start_date!,
          target: entry.patch.target_date!,
        }));
        const cascade = cascadePlanMulti(model.rows, seeds);
        if (cascade.truncated) {
          pushToast(
            `More than ${ROADMAP_CASCADE_MAX_ITEMS} dependent items — cascade skipped, only ${row.item.key} and its children were moved.`,
          );
          append(epicStretchPatches(model.rows, seeds));
        } else {
          append(cascade.patches);
          if (cascade.cascadedCount > 0) {
            const count = cascade.cascadedCount;
            onSuccess = () =>
              pushToast(`Rescheduled ${count} dependent item${count === 1 ? "" : "s"}`);
          }
        }
        applyPatches(patches, onSuccess, `Move ${row.item.key} + children`);
        return;
      }

      const patch: ItemUpdate = {};
      if (start !== row.item.start_date) patch.start_date = start;
      if (target !== row.item.target_date) patch.target_date = target;
      if (patch.start_date === undefined && patch.target_date === undefined) return;
      patches.push({ itemId: row.item.id, patch, optimistic: { ...patch } });
      const move: RoadmapMove = { itemId: row.item.id, start, target };

      // The cascade fires only on commits that CHANGE the target date; Alt at
      // drop is the escape hatch (documented on the Dependencies toggle).
      if (patch.target_date === undefined || modifiers.alt) {
        append(epicStretchPatches(model.rows, [move]));
      } else {
        const plan = cascadePlan(model.rows, row.item.id, { start, target });
        if (plan.truncated) {
          pushToast(
            `More than ${ROADMAP_CASCADE_MAX_ITEMS} dependent items — cascade skipped, only ${row.item.key} was moved.`,
          );
          append(epicStretchPatches(model.rows, [move]));
        } else {
          append(plan.patches);
          if (plan.cascadedCount > 0) {
            const count = plan.cascadedCount;
            onSuccess = () =>
              pushToast(`Rescheduled ${count} dependent item${count === 1 ? "" : "s"}`);
          }
        }
      }
      applyPatches(patches, onSuccess, `Reschedule ${row.item.key}`);
    },
    [model, applyPatches],
  );

  /**
   * Schedule an unscheduled item dropped from the tray: start = the drop day
   * (today when the timeline is still empty), target = start + the kind's
   * default span.
   */
  const scheduleFromTray = useCallback(
    (item: Item, dayIndex: number | null) => {
      const start =
        dayIndex !== null && model.domainStart
          ? isoFromDay(model.domainStart, dayIndex)
          : todayIso();
      const spanDays =
        item.kind === ItemKind.epic ? ROADMAP_EPIC_SPAN_DAYS : ROADMAP_LEAF_SPAN_DAYS;
      const target = shiftIso(start, spanDays);
      // Direct draft push: the tray item is not in the roadmap's base fetch,
      // so the op carries the full Item (draft-wave INSERT) for drawing.
      draft.pushOp({
        kind: "patch",
        label: `Schedule ${item.key}`,
        patches: [
          { itemId: item.id, after: { start_date: start, target_date: target }, insert: item },
        ],
      });
    },
    [model.domainStart, draft],
  );

  /** ○-handle drop (spec 78): open the type popover at the drop point. */
  const beginLink = useCallback(
    (row: RoadmapRow, targetItemId: string, x: number, y: number) => {
      const target = model.rows.find((candidate) => candidate.item.id === targetItemId);
      if (!target) return;
      setLinkAnchor({
        x,
        y,
        sourceId: row.item.id,
        sourceKey: row.item.key,
        targetId: targetItemId,
        targetKey: target.item.key,
      });
    },
    [model.rows],
  );

  /** Connector click (spec 78): open the popover on an existing link. */
  const openLinkEditor = useCallback((edge: ConnectorEdge, x: number, y: number) => {
    setLinkAnchor({
      x,
      y,
      sourceId: edge.sourceId,
      sourceKey: edge.sourceKey,
      targetId: edge.targetId,
      targetKey: edge.targetKey,
      linkId: edge.linkId,
      linkType: edge.linkType,
    });
  }, []);

  /** DELETE a link outright (popover Remove + the Dependencies submenu). */
  const deleteLink = useCallback(
    (itemId: string, linkId: string) => {
      removeLink.mutate(
        { itemId, linkId },
        { onError: (error) => pushToast(errorMessage(error)) },
      );
    },
    [removeLink],
  );

  /**
   * Popover type pick: creating POSTs with the chosen type; editing retypes
   * via DELETE-then-POST in one chain (no PATCH on links server-side) — either
   * step failing toasts once, and the settle invalidation refetches truth.
   */
  const pickLinkType = useCallback(
    (type: string) => {
      if (!linkAnchor) return;
      setLinkAnchor(null);
      const body = { target_id: linkAnchor.targetId, link_type: type };
      if (linkAnchor.linkId) {
        if (type === linkAnchor.linkType) return;
        void removeLink
          .mutateAsync({ itemId: linkAnchor.sourceId, linkId: linkAnchor.linkId })
          .then(() => addLink.mutateAsync({ itemId: linkAnchor.sourceId, body }))
          .catch((error: unknown) => pushToast(errorMessage(error)));
        return;
      }
      addLink.mutate(
        { itemId: linkAnchor.sourceId, body },
        { onError: (error) => pushToast(errorMessage(error)) },
      );
    },
    [linkAnchor, addLink, removeLink],
  );

  /** Popover "Remove link". */
  const removeAnchorLink = useCallback(() => {
    if (linkAnchor?.linkId) deleteLink(linkAnchor.sourceId, linkAnchor.linkId);
    setLinkAnchor(null);
  }, [linkAnchor, deleteLink]);

  /**
   * Vertical row reorder (spec 82): a label drop on the top/bottom half of a
   * SIBLING persists through the spec-24 global rank PATCH, anchored on the
   * adjacent siblings from the model's row order — optimistic against the
   * view's paged item cache (`useReorderItem`, the ViewList idiom; the same
   * `viewItems` key `useRoadmapItemPatch` paints). Non-sibling drops resolve
   * to null and do nothing.
   */
  const reorderRow = useCallback(
    (moved: RoadmapRow, target: RoadmapRow, before: boolean) => {
      const neighbours = roadmapReorderNeighbours(model.rows, moved, target, before);
      if (!neighbours) return;
      draft.pushOp({
        kind: "reorder",
        label: `Reorder ${moved.item.key}`,
        itemId: moved.item.id,
        afterId: neighbours.afterId,
        beforeId: neighbours.beforeId,
      });
    },
    [model.rows, draft],
  );

  /**
   * Rewrite ranks to match `orderedIds` via a SEQUENTIAL after_id chain
   * (spec 82): item[i] ranks after item[i-1], each PATCH anchoring on the
   * previous item's fresh rank — so the awaits must be sequential. The first
   * item stays put; ranks are global, so the chain deliberately touches ONLY
   * the ordered set (epics/children interleave — no epic anchor). One error
   * toast + stop on failure; ONE item-entity invalidation at the end either
   * way (no optimistic paint — the refetch snaps the rows over).
   */
  const applyRankChain = useCallback(
    // Draft wave: the chain is recorded as one op (the sequential rank PATCHes
    // replay at Save).
    (orderedIds: string[], onSuccess?: () => void) => {
      if (orderedIds.length < RANK_CHAIN_MIN_ITEMS) return;
      draft.pushOp({
        kind: "chain",
        label: `Order ${orderedIds.length} rows by date`,
        orderedIds,
      });
      onSuccess?.();
    },
    [draft],
  );

  /** "Order children by date" (spec 82): date-sort the epic's loaded
   *  children (start asc nulls-last, target asc, key), then the rank chain. */
  const orderChildrenByDate = useCallback(
    (row: RoadmapRow) => {
      const ordered = childrenDateOrder(row.children);
      if (ordered.length < RANK_CHAIN_MIN_ITEMS) return;
      applyRankChain(
        ordered.map((child) => child.id),
        // Always >= RANK_CHAIN_MIN_ITEMS here, so plural is safe.
        () => pushToast(`Ordered ${ordered.length} children by date`),
      );
    },
    [applyRankChain],
  );

  return {
    collapsedIds: collapsedIds ?? EMPTY_SET,
    toggleCollapse,
    setAllCollapsed,
    saveDraft,
    saving,
    menu,
    openMenu: (row: RoadmapRow, x: number, y: number) => setMenu({ row, x, y }),
    closeMenu: () => setMenu(null),
    applyPatches,
    commitSpan,
    scheduleFromTray,
    reorderRow,
    applyRankChain,
    orderChildrenByDate,
    linkAnchor,
    beginLink,
    openLinkEditor,
    pickLinkType,
    removeAnchorLink,
    closeLinkPopover: () => setLinkAnchor(null),
    deleteLink,
  };
}
