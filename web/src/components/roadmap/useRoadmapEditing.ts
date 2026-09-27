import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "@radd/plugin-sdk";
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
  cascadePlanMulti,
  childrenDateOrder,
  epicMovePlan,
  epicStretchPatches,
  isoDaysBetween,
  isoFromDay,
  roadmapReorderNeighbours,
  type RoadmapModel,
  type RoadmapMove,
  type RoadmapRow,
  type RoadmapSpan,
} from "./roadmap-model";
import { BarDragMode, type CommitModifiers } from "./useBarDrag";
import type { RoadmapDraft } from "./useRoadmapDraft";
import { shiftIsoDay, todayIso } from "@radd/plugin-sdk";

/**
 * Everything stateful about roadmap EDITING, so RoadmapSurface stays chrome:
 * gesture commits (cascade + epic stretch) and plan patches into the draft,
 * Save, tray-drop scheduling, the link popover, the per-VIEW epic collapse set
 * (localStorage), the context-menu anchor, and the rank writes.
 */

interface RoadmapMenuAnchor {
  row: RoadmapRow;
  x: number;
  y: number;
}

/** The link popover's subject: `linkId` present = editing an existing link. */
interface RoadmapLinkAnchor {
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

  /** Record a patch list as ONE draft op (menu verbs, plans); nothing hits the server until Save. */
  const applyPatches = useCallback(
    (patches: RoadmapDatePatch[], label?: string) => {
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
      const patches = draft.netPatches(baseItems);
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
   * Commit a move/resize as ONE draft op (specs 78 + 81): the changed date(s),
   * then — when the target changed and Alt wasn't held — the dependency
   * cascade (skipped past the cap). A BODY move of a non-derived epic is a
   * CONTAINER move: its loaded scheduled children shift by the same delta and
   * the whole set seeds the cascade. Parent-epic outward stretches ride along.
   */
  const commitSpan = useCallback(
    (row: RoadmapRow, span: RoadmapSpan, modifiers: CommitModifiers) => {
      if (!model.domainStart) return;
      const start = isoFromDay(model.domainStart, span.startIndex);
      const target = isoFromDay(model.domainStart, span.endIndex);
      let patches: RoadmapDatePatch[];
      let seeds: RoadmapMove[];
      let cascade: boolean;
      let label: string;
      let moved: string;

      // Epic container move (spec 81): the epic + its loaded scheduled
      // children shift together (RESIZE and Alt keep the single-bar path).
      const containerMove =
        modifiers.mode === BarDragMode.move &&
        !modifiers.alt &&
        row.rowKind === RoadmapRowKind.epic &&
        !row.derived;
      if (containerMove) {
        const deltaDays = isoDaysBetween(row.item.start_date!, start);
        const container = epicMovePlan(model.rows, row.item.id, deltaDays);
        if (container.patches.length === 0) return;
        patches = [...container.patches];
        seeds = container.patches.map((entry) => ({
          itemId: entry.itemId,
          start: entry.patch.start_date!,
          target: entry.patch.target_date!,
        }));
        cascade = true;
        label = `Move ${row.item.key} + children`;
        moved = `${row.item.key} and its children were`;
      } else {
        const patch: ItemUpdate = {};
        if (start !== row.item.start_date) patch.start_date = start;
        if (target !== row.item.target_date) patch.target_date = target;
        if (patch.start_date === undefined && patch.target_date === undefined) return;
        patches = [{ itemId: row.item.id, patch }];
        seeds = [{ itemId: row.item.id, start, target }];
        // The cascade fires only on commits that CHANGE the target date; Alt at
        // drop is the escape hatch (documented on the Dependencies toggle).
        cascade = patch.target_date !== undefined && !modifiers.alt;
        label = `Reschedule ${row.item.key}`;
        moved = `${row.item.key} was`;
      }

      const plan = cascade ? cascadePlanMulti(model.rows, seeds) : null;
      if (plan && plan.truncated) {
        pushToast(
          `More than ${ROADMAP_CASCADE_MAX_ITEMS} dependent items — cascade skipped, only ${moved} moved.`,
        );
      }
      patches.push(...(plan && !plan.truncated ? plan.patches : epicStretchPatches(model.rows, seeds)));
      applyPatches(patches, label);
      if (plan && !plan.truncated && plan.cascadedCount > 0) {
        const count = plan.cascadedCount;
        pushToast(`Rescheduled ${count} dependent issue${count === 1 ? "" : "s"}`);
      }
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
      const target = shiftIsoDay(start, spanDays);
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

  /** Vertical row reorder (spec 82): a drop on the top/bottom half of a
   *  SIBLING records a rank intent anchored on the adjacent siblings;
   *  non-sibling drops do nothing. */
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

  /** Record a rank chain (spec 82) as one draft op: at Save item[i] ranks
   *  after item[i-1], sequentially. Ranks are global, so the chain touches
   *  ONLY the ordered set. */
  const applyRankChain = useCallback(
    (orderedIds: string[]) => {
      if (orderedIds.length < RANK_CHAIN_MIN_ITEMS) return;
      draft.pushOp({
        kind: "chain",
        label: `Order ${orderedIds.length} rows by date`,
        orderedIds,
      });
    },
    [draft],
  );

  /** "Order children by date" (spec 82): date-sort the epic's loaded
   *  children (start asc nulls-last, target asc, key), then the rank chain. */
  const orderChildrenByDate = useCallback(
    (row: RoadmapRow) => {
      const ordered = childrenDateOrder(row.children);
      if (ordered.length < RANK_CHAIN_MIN_ITEMS) return;
      applyRankChain(ordered.map((child) => child.id));
      // Always >= RANK_CHAIN_MIN_ITEMS here, so plural is safe.
      pushToast(`Ordered ${ordered.length} children by date`);
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
