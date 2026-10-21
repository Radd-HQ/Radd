import type { RoadmapPlanPatch } from "./model/planning";
import type { RoadmapDatePatch } from "../../lib/item-mutations";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bookmark,
  ChevronsDownUp,
  ChevronsUpDown,
  Focus,
  GanttChartSquare,
  Gem,
  History,
  Maximize2,
  Redo2,
  Rows3,
  Undo2,
  ZoomIn,
  ZoomOut,
  type LucideIcon,
} from "lucide-react";
import { api } from "../../lib/api";
import { startHorizontalDrag } from "../../lib/drag";
import { useDurationConfig, useIsAuthenticated, useStoredFlag } from "../../lib/hooks";
import {
  cyclesQuery,
  projectTimeloggingQuery,
  roadmapDraftedItemsQuery,
  timelogBatchChunkedQuery,
} from "../../lib/queries";
import {
  ApiPath,
  ITEMS_PAGE_LIMIT,
  ROADMAP_CHILDREN_PAGE_CAP,
  ROADMAP_DAY_WIDTH,
  ROADMAP_EXTEND_STEP_DAYS,
  ROADMAP_FRAME_FILL,
  ROADMAP_LABEL_MAX_WIDTH,
  ROADMAP_LABEL_MIN_WIDTH,
  ROADMAP_LABEL_WIDTH,
  roadmapFlatStorageKey,
  roadmapLabelWidthStorageKey,
  roadmapZoomStorageKey,
  ROADMAP_PROGRESS_STALE_MS,
  ROADMAP_ZOOM_BUTTON_FACTOR,
  ROADMAP_ZOOM_LEVELS,
} from "../../lib/constants";
import { pushToast } from "../../lib/toast";
import { ItemKind, type Item, type View } from "../../lib/types";
import { Button } from "../Button";
import { useConfirm, EmptyState, todayIso } from "@radd/plugin-sdk";
import { Select } from "../Select";
import { useRollupBatch } from "../items/RollupBar";
import { RoadmapTimeline } from "./RoadmapTimeline";
import { RoadmapContextMenu } from "./RoadmapContextMenu";
import { LinkPopover } from "./LinkPopover";
import { UnscheduledTray } from "./UnscheduledTray";
import { useRoadmapEditing } from "./useRoadmapEditing";
import {
  NO_EXTENSION,
  RoadmapRowKind,
  blocksEdges,
  buildRoadmapModel,
  clampDayWidth,
  cycleBands,
  durationDaysFromEstimate,
  fitDayWidth,
  importChildrenPlan,
  parseDay,
  roadmapAxisHeight,
  roadmapRowMetrics,
  spreadChildrenPlan,
  zoomPercentLabel,
  type RoadmapExtension,
  type RoadmapRow,
} from "./roadmap-model";
import { RoadmapSelectionMenu } from "./RoadmapSelectionMenu";
import { useRoadmapDraft } from "./useRoadmapDraft";
import { useRoadmapViewport } from "./useRoadmapViewport";
import { ExtendDirection, type ExtendDirectionValue } from "./useBarDrag";
import { MOD_KEY, modShortcut, shiftModShortcut } from "../../lib/platform";
import type { Project } from "@radd-plugin-ui/projects/types";

interface RoadmapSurfaceProps {
  /** The saved view being rendered (spec 79): `id` keys the per-view
   *  localStorage state, `query_string` keys the item cache gestures paint. */
  view: Pick<View, "id" | "query_string">;
  /** The view's project — null = all-projects (bars/tray span readable
   *  projects; link creation across projects 409s server-side → toast). */
  project: Project | null;
  /** Already fetched AND filtered by the caller (fetch-all + quick filters +
   *  the ad-hoc SLQ bar) — the surface never fetches items itself. */
  items: Item[];
  /** item.update in the view's scope (the same rule other view types use for
   *  drag gating) — false renders the read-only timeline. */
  canUpdate: boolean;
  /** The view has no explicit ORDER BY (or orders by rank), so rows follow
   *  the global manual rank (spec 82) — computed by the view page with the
   *  same regex rule lists use. Gates vertical reorder + the date-order verb. */
  rankOrdered: boolean;
  /** True while a caller-side filter narrows the set — tunes the empty state. */
  filtered: boolean;
  /** Tray base SLQ (view query + tray clause) — the tray pages it itself. */
  trayQuery: string;
  trayProjectId: string | null;
  /** "Show closed": false = done/canceled items are not drawn at all (RADD-946). */
  showClosed: boolean;
  onToggleShowClosed: () => void;
  /** "Epics only": only epics + their scheduled children draw (standalone
   *  leaves drown out). The owner narrows the fetch to match. */
  epicsOnly: boolean;
  onToggleEpicsOnly: () => void;
  /** Curated membership (roadmap wave): pinned-item count, the Members/All
   *  toggle, per-row member state, and the pin/unpin verb. Curation follows
   *  view EDIT rights (owner/editor), not item.update. */
  membersCount: number;
  membersOnly: boolean;
  onToggleMembersOnly: () => void;
  memberIds: ReadonlySet<string>;
  onToggleMember: (itemId: string, makeMember: boolean) => void;
  onToggleMembers: (itemIds: string[], makeMember: boolean) => void;
  canCurate: boolean;
  /** True when the auto-fetch paused at its page cap — more rows exist. */
  truncated: boolean;
  onLoadMore: () => void;
}

/**
 * Roadmap / Gantt view surface (specs 19/77/78/79/81/82): dated items as bars
 * on a week/month axis, epics as expandable rows over their children. With
 * item.update it is a planning editor whose gestures edit a local DRAFT that
 * only Save writes (useRoadmapDraft); otherwise the read-only timeline. Rows
 * are RANK-STABLE (spec 82): fetch order is row order and date order is an
 * explicit verb. Mount with `key={view.id}` so zoom, extension, collapse and
 * tray state re-initialize per view.
 */
export function RoadmapSurface({
  view,
  project,
  items,
  canUpdate,
  rankOrdered,
  filtered,
  trayQuery,
  trayProjectId,
  showClosed,
  onToggleShowClosed,
  epicsOnly,
  onToggleEpicsOnly,
  membersCount,
  membersOnly,
  onToggleMembersOnly,
  memberIds,
  onToggleMember,
  onToggleMembers,
  canCurate,
  truncated,
  onLoadMore,
}: RoadmapSurfaceProps) {
  // Session-only "+1 month" domain growth (spec 78) — per mount (= per view).
  const [extension, setExtension] = useState<RoadmapExtension>(NO_EXTENSION);
  const extendDomain = useCallback((direction: ExtendDirectionValue) => {
    setExtension((previous) =>
      direction === ExtendDirection.before
        ? { ...previous, extendBeforeDays: previous.extendBeforeDays + ROADMAP_EXTEND_STEP_DAYS }
        : { ...previous, extendAfterDays: previous.extendAfterDays + ROADMAP_EXTEND_STEP_DAYS },
    );
  }, []);

  // Gestures edit a LOCAL draft (useRoadmapDraft); only Save writes.
  const draft = useRoadmapDraft();
  // RADD-1506: rows the draft INSERTED exist nowhere in the server fetch, so
  // their snapshot would freeze at gesture time — a dependency drawn from one
  // never appeared until Save + reload. Fetch them live by key (the query is
  // item-tagged, so every link/item write refetches it) and fold the draft
  // over `base ∪ fresh`; the snapshot stays the fallback until the first
  // fetch lands, so nothing flickers.
  const loadedIds = useMemo(() => new Set(items.map((item) => item.id)), [items]);
  const draftedKeys = useMemo(
    () =>
      draft.insertedItems
        .filter((item) => !loadedIds.has(item.id))
        .map((item) => item.key)
        .sort(),
    [draft.insertedItems, loadedIds],
  );
  const draftedRows = useQuery({
    ...roadmapDraftedItemsQuery(draftedKeys, project?.id ?? null),
    enabled: draftedKeys.length > 0,
  });
  const baseItems = useMemo(() => {
    const fresh = draftedRows.data;
    if (!fresh || fresh.length === 0) return items;
    return [...items, ...fresh.filter((item) => !loadedIds.has(item.id))];
  }, [items, loadedIds, draftedRows.data]);
  const draftedItems = useMemo(() => draft.applyTo(baseItems), [draft, baseItems]);
  useEffect(() => {
    if (!draft.dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [draft.dirty]);

  // Solo: a non-empty set builds the model from ONLY the soloed epics + their
  // children (rows AND domain). Session-only — a persisted solo reads as data loss.
  const [soloIds, setSoloIds] = useState<ReadonlySet<string>>(() => new Set());
  const modelItems = useMemo(() => {
    const epicIds = new Set(
      draftedItems.filter((item) => item.kind === ItemKind.epic).map((item) => item.id),
    );
    return draftedItems.filter((item) => {
      // Epics-only: a non-epic draws only NESTED under a loaded epic, never as a
      // standalone row (a belt to the fetch clause).
      if (
        epicsOnly &&
        item.kind !== ItemKind.epic &&
        !(item.parent && epicIds.has(item.parent.id))
      ) {
        return false;
      }
      if (soloIds.size === 0) return true;
      return soloIds.has(item.id) || (item.parent && soloIds.has(item.parent.id));
    });
  }, [draftedItems, soloIds, epicsOnly]);
  // Flat (RADD-1511): no epic rows, every scheduled issue its own row with
  // its epic as a chip — the cycle-centric reading. Persisted per view.
  const [flat, toggleFlat] = useStoredFlag(roadmapFlatStorageKey(view.id));
  const model = useMemo(
    () => buildRoadmapModel(modelItems, todayIso(), extension, flat),
    [modelItems, extension, flat],
  );
  // Cycle bands (RADD-1511): the dated cycles this project plans with (every
  // cycle, on an all-projects roadmap) as labelled spans on the axis.
  const authenticated = useIsAuthenticated();
  const cycles = useQuery({ ...cyclesQuery(undefined, project?.id), enabled: authenticated });
  const bands = useMemo(() => cycleBands(cycles.data ?? [], model), [cycles.data, model]);

  const editing = useRoadmapEditing(view, model, draft, baseItems);
  const [confirmDialog, confirm] = useConfirm();
  const discardDraft = async () => {
    const ok = await confirm({
      title: "Discard roadmap changes",
      message: `Throw away ${draft.changedCount} unsaved change${
        draft.changedCount === 1 ? "" : "s"
      }? The undo history goes with them.`,
      confirmLabel: "Discard",
      danger: true,
    });
    if (ok) {
      draft.clear();
      editing.clearSaveError();
    }
  };
  const toggleSolo = useCallback(
    (epicId: string) => {
      const adding = !soloIds.has(epicId);
      setSoloIds((previous) => {
        const next = new Set(previous);
        if (next.has(epicId)) next.delete(epicId);
        else next.add(epicId);
        return next;
      });
      // Soloing is for scheduling the epic's children — surface them.
      if (adding && editing.collapsedIds.has(epicId)) editing.toggleCollapse(epicId);
    },
    [soloIds, editing],
  );
  const collapsibleEpicIds = useMemo(
    () =>
      model.rows
        .filter((row) => row.rowKind === RoadmapRowKind.epic && row.scheduledChildCount > 0)
        .map((row) => row.item.id),
    [model.rows],
  );
  // Zoom = the day width, remembered per view (RADD-1520) the way the label
  // gutter is: a planner comes back to the level they left, not the default.
  // Only a user change writes; a view switch re-reads.
  const [dayWidth, setDayWidthState] = useState(() => storedDayWidth(view.id));
  useEffect(() => {
    setDayWidthState(storedDayWidth(view.id));
  }, [view.id]);
  const setDayWidth = useCallback(
    (width: number) => {
      const next = clampDayWidth(width);
      setDayWidthState(next);
      window.localStorage.setItem(roadmapZoomStorageKey(view.id), String(next));
    },
    [view.id],
  );
  const [showConnectors, setShowConnectors] = useState(true);
  const [trayDragItem, setTrayDragItem] = useState<Item | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Timelog seconds: ONE chunked batch over every leaf row plus every epic's
  // loaded children (tints + auto-schedule durations). Viewers included; any
  // failure/disabled/estimate-less project degrades quietly to no tint and
  // default durations. Generous staleTime, no polling — roadmaps can be huge.
  const durationConfig = useDurationConfig();
  const timelogging = useQuery({
    ...projectTimeloggingQuery(project?.id ?? ""),
    enabled: Boolean(project),
    retry: false,
  });
  const timeloggingOn = project ? timelogging.data?.enabled === true : true;
  const timelogItemIds = useMemo(() => {
    const ids = new Set<string>();
    for (const row of model.rows) {
      if (row.rowKind === RoadmapRowKind.epic) {
        for (const child of row.children) ids.add(child.id);
      } else {
        ids.add(row.item.id);
      }
    }
    return [...ids];
  }, [model.rows]);
  const timelogBatch = useQuery({
    ...timelogBatchChunkedQuery(timelogItemIds),
    enabled: authenticated && timeloggingOn && timelogItemIds.length > 0,
    staleTime: ROADMAP_PROGRESS_STALE_MS,
  });
  // Epic tint fractions (done/total children) — the spec-76 rollup batch over
  // the epic row ids; same lazy quiet-degrade posture (an epic past the
  // 200-id cap simply renders untinted).
  const epicRowIds = useMemo(
    () =>
      model.rows
        .filter((row) => row.rowKind === RoadmapRowKind.epic)
        .map((row) => row.item.id),
    [model.rows],
  );
  const rollupByItem = useRollupBatch(
    epicRowIds,
    epicRowIds.length > 0,
    ROADMAP_PROGRESS_STALE_MS,
  );
  // Every drawn row — a date-less epic with a derived (children-union) bar
  // also matches the tray's unscheduled query, so the tray dedupes against it.
  const rowItemIds = useMemo(
    () => new Set(model.rows.map((row) => row.item.id)),
    [model.rows],
  );

  // Perf wave: the main fetch carries only epics + dated bars, so an epic's
  // full child list (date-less ones included) is fetched HERE, when a verb
  // actually needs it — `parent = KEY` is exact and epic-bounded, not
  // project-bounded, so a couple of pages cover any sane epic.
  const queryClient = useQueryClient();
  const fetchEpicChildren = useCallback(async (epic: Item): Promise<Item[]> => {
    const collected: Item[] = [];
    for (let page = 0; page < ROADMAP_CHILDREN_PAGE_CAP; page++) {
      const batch = await api.get<Item[]>(ApiPath.items, {
        query: {
          q: `parent = ${epic.key}`,
          limit: String(ITEMS_PAGE_LIMIT),
          offset: String(page * ITEMS_PAGE_LIMIT),
        },
      });
      collected.push(...batch);
      if (batch.length < ITEMS_PAGE_LIMIT) break;
    }
    return collected;
  }, []);
  /** The epic's children for a verb — toasts (and yields null) when the
   *  fetch fails or the epic has none. */
  const loadChildren = useCallback(
    async (row: RoadmapRow): Promise<Item[] | null> => {
      let children: Item[];
      try {
        children = await fetchEpicChildren(row.item);
      } catch {
        pushToast("Couldn't load the epic's children");
        return null;
      }
      if (children.length === 0) {
        pushToast("This epic has no children");
        return null;
      }
      return children;
    },
    [fetchEpicChildren],
  );
  /** Children + their estimate batch (durations) — the scheduling verbs' inputs. */
  const loadChildrenWithEstimates = useCallback(
    async (row: RoadmapRow): Promise<{ children: Item[]; durations: Map<string, number> } | null> => {
      const children = await loadChildren(row);
      if (!children) return null;
      const durations = new Map<string, number>();
      if (timeloggingOn) {
        const batch = await queryClient
          .fetchQuery(timelogBatchChunkedQuery(children.map((child) => child.id)))
          .catch(() => undefined);
        for (const child of children) {
          const estimate = batch?.[child.id]?.estimate_seconds;
          if (estimate && estimate > 0) {
            durations.set(child.id, durationDaysFromEstimate(estimate, durationConfig.hoursPerDay));
          }
        }
      }
      return { children, durations };
    },
    [loadChildren, timeloggingOn, queryClient, durationConfig.hoursPerDay],
  );

  // RADD-1151: a plan's patches must DRAW before Save like a tray drop does.
  // The roadmap fetch loads scheduled items only, so an epic's unscheduled
  // children exist nowhere in the base set — each such patch carries the
  // loaded child as the draft-wave INSERT, and the row appears at once.
  const withInserts = useCallback(
    (patches: RoadmapPlanPatch[], children: Item[]): RoadmapDatePatch[] => {
      const loaded = new Set(items.map((item) => item.id));
      const byId = new Map(children.map((child) => [child.id, child]));
      return patches.map(({ itemId, patch }) => ({
        itemId,
        patch,
        insert: loaded.has(itemId) ? undefined : byId.get(itemId),
      }));
    },
    [items],
  );

  // "Spread children across the epic" (RADD-1510): a layout verb — equal
  // back-to-back slots across the epic's OWN window, no estimates involved.
  // The one layout verb since RADD-1514 (the thread's call: auto-schedule's
  // estimate-sized packing "means nothing scheduling wise").
  const handleSpreadChildren = useCallback(
    async (row: RoadmapRow) => {
      const children = await loadChildren(row);
      if (!children) return;
      const plan = spreadChildrenPlan(children, blocksEdges(children), row.item);
      if (plan.patches.length === 0) return;
      // Spec 82: on a rank-ordered view the children also rank in slot order
      // so the result reads top-to-bottom — one undo step with the dates
      // (RADD-1510 / RADD-1433); a view with its own ORDER BY gets no chain.
      editing.applyPlan(
        withInserts(plan.patches, children),
        `Spread ${row.item.key}'s children`,
        rankOrdered ? plan.orderedIds : null,
      );
      const count = plan.spreadCount;
      pushToast(`Spread ${count} ${count === 1 ? "child" : "children"} across ${row.item.key}`);
    },
    [loadChildren, editing, withInserts, rankOrdered],
  );

  // "Bring children into roadmap": the as-is placement — only MISSING dates
  // fill, at the epic's start, estimate-sized or one day. The one verb that
  // reads estimates now that auto-schedule is gone (RADD-1514).
  const handleImportChildren = useCallback(
    async (row: RoadmapRow) => {
      const loaded = await loadChildrenWithEstimates(row);
      if (!loaded) return;
      const plan = importChildrenPlan(
        loaded.children,
        row.item,
        row.item.start_date ?? todayIso(),
        loaded.durations,
      );
      if (plan.patches.length === 0) {
        pushToast("All children are already scheduled");
        return;
      }
      const count = plan.importedCount;
      editing.applyPatches(withInserts(plan.patches, loaded.children), `Bring ${row.item.key}'s children in`);
      pushToast(`Brought ${count} ${count === 1 ? "child" : "children"} into the roadmap`);
    },
    [loadChildrenWithEstimates, editing, withInserts],
  );

  // Collapsed epics hide their child rows (chevron state is per-view).
  const visibleRows = useMemo(
    () =>
      model.rows.filter(
        (row) => !row.parentEpicId || !editing.collapsedIds.has(row.parentEpicId),
      ),
    [model.rows, editing.collapsedIds],
  );

  const scheduledCount = model.rows.length;

  const emptyDropProps =
    canUpdate && trayDragItem
      ? {
          onDragOver: (event: ReactDragEvent<HTMLElement>) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
          },
          onDrop: (event: ReactDragEvent<HTMLElement>) => {
            event.preventDefault();
            editing.scheduleFromTray(trayDragItem, null);
            setTrayDragItem(null);
          },
        }
      : {};

  // Label-gutter width: dragged by the divider, persisted per view. NOT a
  // collapse — these labels are the timeline's y-axis, and a bar with no row
  // label is an anonymous rectangle. Resizing gives the width back without
  // costing row identity.
  const [labelWidth, setLabelWidth] = useState(ROADMAP_LABEL_WIDTH);
  useEffect(() => {
    const stored = Number(window.localStorage.getItem(roadmapLabelWidthStorageKey(view.id)));
    if (Number.isFinite(stored) && stored > 0) {
      setLabelWidth(Math.min(ROADMAP_LABEL_MAX_WIDTH, Math.max(ROADMAP_LABEL_MIN_WIDTH, stored)));
    }
  }, [view.id]);

  const startLabelResize = (event: ReactPointerEvent) =>
    startHorizontalDrag(event, {
      start: labelWidth,
      min: ROADMAP_LABEL_MIN_WIDTH,
      max: ROADMAP_LABEL_MAX_WIDTH,
      onMove: setLabelWidth,
      onEnd: (final) =>
        window.localStorage.setItem(roadmapLabelWidthStorageKey(view.id), String(final)),
    });

  // Viewport navigation (DCC-style): middle-mouse pan + ctrl-wheel cursor-
  // anchored zoom; zoomBy also backs the toolbar ± buttons.
  const axisHeight = roadmapAxisHeight(bands.length > 0);
  const { zoomBy } = useRoadmapViewport(scrollRef, labelWidth, axisHeight, dayWidth, setDayWidth);

  // Selection (viewport wave): label clicks select (ctrl/meta toggles), the
  // timeline's rubber band multi-selects, F frames the selection, Escape
  // clears it, and right-clicking a selected row opens the BULK menu.
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(() => new Set());
  const [selectionMenu, setSelectionMenu] = useState<{ x: number; y: number } | null>(null);
  const selectRow = useCallback((itemId: string, additive: boolean) => {
    setSelectedIds((previous) => {
      if (!additive) return new Set([itemId]);
      const next = new Set(previous);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }, []);
  const rubberSelect = useCallback((ids: string[], additive: boolean) => {
    setSelectedIds((previous) => (additive ? new Set([...previous, ...ids]) : new Set(ids)));
  }, []);
  const selectedItems = useMemo(
    () => modelItems.filter((item) => selectedIds.has(item.id)),
    [modelItems, selectedIds],
  );

  /** Frame the selection (F): zoom so its span fills most of the pane, then
   *  center it both axes — the DCC "frame selected" verb. */
  const frameSelection = useCallback(() => {
    const el = scrollRef.current;
    if (!el || selectedIds.size === 0) return;
    const rows = model.rows.filter((row) => selectedIds.has(row.item.id));
    if (rows.length === 0) return;
    anchoredRef.current = false; // manual navigation from here on
    const minStart = Math.min(...rows.map((row) => row.startIndex));
    const maxEnd = Math.max(...rows.map((row) => row.endIndex));
    const spanDays = Math.max(maxEnd - minStart + 1, 1);
    const visible = Math.max(el.clientWidth - labelWidth, 100);
    const targetW = clampDayWidth((visible * ROADMAP_FRAME_FILL) / spanDays);
    setDayWidth(targetW);
    const firstRowIndex = Math.min(
      ...rows.map((row) => visibleRows.findIndex((r) => r.item.id === row.item.id)).filter((i) => i >= 0),
    );
    requestAnimationFrame(() => {
      el.scrollLeft = Math.max(0, minStart * targetW - (visible - spanDays * targetW) / 2);
      if (Number.isFinite(firstRowIndex)) {
        // Rows start after the axis header (plus the cycle strip) in the
        // scroll content, at the pitch the NEW zoom gives them.
        const { rowH } = roadmapRowMetrics(targetW);
        el.scrollTop = Math.max(0, axisHeight + firstRowIndex * rowH - el.clientHeight / 2);
      }
    });
  }, [scrollRef, selectedIds, model.rows, visibleRows, labelWidth, axisHeight, setDayWidth]);

  /** Fit (A): the whole domain in the visible timeline width, from the origin
   *  — the DCC "frame all" verb beside F. The rows follow the day width down,
   *  so a long domain also shows far more of the plan vertically. */
  const fitAll = useCallback(() => {
    const el = scrollRef.current;
    if (!el || model.domainDays === 0) return;
    anchoredRef.current = false; // manual navigation from here on
    setDayWidth(fitDayWidth(el.clientWidth - labelWidth, model.domainDays));
    requestAnimationFrame(() => {
      el.scrollLeft = 0;
      el.scrollTop = 0;
    });
  }, [scrollRef, model.domainDays, labelWidth, setDayWidth]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)
      ) {
        return;
      }
      if (event.key === "f" || event.key === "F") {
        frameSelection();
      } else if (event.key === "a" || event.key === "A") {
        fitAll();
      } else if (event.key === "Escape") {
        setSelectedIds(new Set());
        setSelectionMenu(null);
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) draft.redo();
        else draft.undo();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        draft.redo();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [frameSelection, fitAll, draft]);

  // Keep TODAY in view: the domain begins at the earliest loaded bar (often
  // years back). Anchor today ~1/3 into the timeline, re-applied as pages
  // stream in and on zoom, but DISENGAGED once the user scrolls or drags so it
  // never fights a human. The Today button re-engages it.
  const anchoredRef = useRef(true);
  const anchorToToday = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      const el = scrollRef.current;
      if (!el || model.domainStart === null) return;
      const timelineWidth = Math.max(el.clientWidth - labelWidth, 0);
      const index =
        model.todayIndex ??
        (parseDay(todayIso()) < model.domainStart ? 0 : model.domainDays);
      el.scrollTo({ left: Math.max(0, index * dayWidth - timelineWidth / 3), behavior });
    },
    [model.domainStart, model.todayIndex, model.domainDays, dayWidth, labelWidth],
  );
  useEffect(() => {
    if (anchoredRef.current) anchorToToday();
  }, [anchorToToday]);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const disengage = () => {
      anchoredRef.current = false;
    };
    el.addEventListener("wheel", disengage, { passive: true });
    el.addEventListener("pointerdown", disengage);
    el.addEventListener("keydown", disengage);
    return () => {
      el.removeEventListener("wheel", disengage);
      el.removeEventListener("pointerdown", disengage);
      el.removeEventListener("keydown", disengage);
    };
  }, []);
  const scrollToToday = () => {
    anchoredRef.current = true;
    anchorToToday("smooth");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* The roadmap's own knobs (no DisplayMenu here): zoom, Today, dependency lines. */}
      <div className="flex items-center gap-2 border-b border-subtle/70 px-5 py-2">
        <Select
          value={String(dayWidth)}
          onChange={(width) => setDayWidth(Number(width))}
          title="Zoom (day width)"
          aria-label="Zoom (day width)"
          size="sm"
          options={[
            ...ROADMAP_ZOOM_LEVELS.map((zoom) => ({
              value: String(zoom.width),
              label: zoom.label,
            })),
            // Ctrl+wheel / ± / Fit leave the presets — show where we landed,
            // as a share of the default: "22%" reads, "2.0px" did not.
            ...(ROADMAP_ZOOM_LEVELS.some((zoom) => zoom.width === dayWidth)
              ? []
              : [{ value: String(dayWidth), label: zoomPercentLabel(dayWidth) }]),
          ]}
        />
        <ToolbarIconButton
          icon={ZoomOut}
          label="Zoom out"
          title="Zoom out (or ctrl+wheel on the timeline)"
          onClick={() => zoomBy(1 / ROADMAP_ZOOM_BUTTON_FACTOR)}
        />
        <ToolbarIconButton
          icon={ZoomIn}
          label="Zoom in"
          title="Zoom in (or ctrl+wheel on the timeline)"
          onClick={() => zoomBy(ROADMAP_ZOOM_BUTTON_FACTOR)}
        />
        <ToolbarIconButton
          icon={Maximize2}
          label="Fit the whole timeline"
          title="Fit the whole timeline in view (A) — F frames the selection"
          onClick={fitAll}
          disabled={model.domainDays === 0}
          disabledClass="opacity-50 pointer-events-none"
        />
        <button
          type="button"
          onClick={scrollToToday}
          disabled={model.todayIndex === null}
          title="Scroll the today line into view"
          className="h-7 rounded-md border border-strong px-2 text-xs text-fg hover:border-emphasis hover:text-heading cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
        >
          Today
        </button>
        <ToolbarToggle
          pressed={showConnectors}
          onClick={() => setShowConnectors((value) => !value)}
          title="Draw dependency lines between visible bars — click one to retype or remove it. Moving a bar pushes its blocks-dependents along; moving an epic slides its scheduled children with it. Hold Alt while dropping to move just that bar — no children, no cascade."
        >
          Dependencies
        </ToolbarToggle>
        <ToolbarIconButton
          icon={ChevronsDownUp}
          label="Collapse all epics"
          title="Collapse all epics"
          onClick={() => editing.setAllCollapsed(collapsibleEpicIds)}
          disabled={collapsibleEpicIds.length === 0}
          disabledClass="disabled:opacity-50 disabled:pointer-events-none"
        />
        <ToolbarIconButton
          icon={ChevronsUpDown}
          label="Expand all epics"
          title="Expand all epics"
          onClick={() => editing.setAllCollapsed([])}
          disabled={editing.collapsedIds.size === 0}
          disabledClass="disabled:opacity-50 disabled:pointer-events-none"
        />
        {(membersCount > 0 || membersOnly) && (
          <ToolbarToggle
            pressed={membersOnly}
            onClick={onToggleMembersOnly}
            icon={Bookmark}
            title={
              membersOnly
                ? "Showing only this roadmap's pinned members (and their children) — click for everything."
                : "Show only the issues pinned to this roadmap."
            }
          >
            Members · {membersCount}
          </ToolbarToggle>
        )}
        {soloIds.size > 0 && (
          <button
            type="button"
            onClick={() => setSoloIds(new Set())}
            title="Solo is on — only the soloed epics and their children are shown. Click to unsolo all."
            className="flex h-7 items-center gap-1 rounded-md border border-accent/60 bg-accent/15 px-2 text-xs text-accent-text cursor-pointer hover:bg-accent/25"
          >
            <Focus size={12} aria-hidden />
            Solo · {soloIds.size} — clear
          </button>
        )}
        <ToolbarToggle
          pressed={epicsOnly}
          onClick={onToggleEpicsOnly}
          icon={Gem}
          title="Drown out the noise: only epics and their scheduled children draw — standalone scheduled issues and subtasks are hidden."
        >
          Epics only
        </ToolbarToggle>
        <ToolbarToggle
          pressed={flat}
          onClick={toggleFlat}
          icon={Rows3}
          title={
            flat
              ? "Flat is on: epic rows are hidden and every scheduled issue is its own row, its epic as a chip — the cycle-centric reading. Click to group under epics again."
              : "Flat: hide the epic rows and list only the scheduled issues, each with its epic as a chip — what a cycle-centric roadmap reads like. Pair it with a cycle filter in the view's query."
          }
        >
          Flat
        </ToolbarToggle>
        <ToolbarToggle
          pressed={showClosed}
          onClick={onToggleShowClosed}
          icon={History}
          title="Done and canceled issues are hidden — toggle to draw finished work alongside what is live."
        >
          Show closed
        </ToolbarToggle>
        {truncated && (
          <span className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-meta text-fg-secondary">
            Showing the first {items.length.toLocaleString()} matches — refine the query, or
            <button
              type="button"
              onClick={onLoadMore}
              className="font-medium text-accent-text hover:underline cursor-pointer"
            >
              load more
            </button>
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {canUpdate && (
            <>
              <ToolbarIconButton
                icon={Undo2}
                label="Undo"
                title={draft.undoLabel ? `Undo: ${draft.undoLabel} (${modShortcut("Z")})` : "Nothing to undo"}
                onClick={draft.undo}
                disabled={!draft.canUndo}
                disabledClass="disabled:opacity-40 disabled:pointer-events-none"
              />
              <ToolbarIconButton
                icon={Redo2}
                label="Redo"
                title={draft.redoLabel ? `Redo: ${draft.redoLabel} (${shiftModShortcut("Z")})` : "Nothing to redo"}
                onClick={draft.redo}
                disabled={!draft.canRedo}
                disabledClass="disabled:opacity-40 disabled:pointer-events-none"
              />
              {editing.saveError && (
                // RADD-1505: a refused save stays visible beside the button,
                // item named, until the next attempt or a Discard — a toast
                // was the only signal before, and it read as "saved".
                <span
                  role="alert"
                  data-save-error
                  title={editing.saveError}
                  className="max-w-xs truncate rounded-md border border-status-danger/40 bg-status-danger/10 px-2 py-0.5 text-meta text-status-danger-ink"
                >
                  Save refused — {editing.saveError}
                </span>
              )}
              {draft.dirty && (
                <Button variant="ghost" size="sm" onClick={() => void discardDraft()}>
                  Discard
                </Button>
              )}
              <Button
                size="sm"
                disabled={!draft.dirty || editing.saving}
                onClick={() => void editing.saveDraft()}
                title={`Nothing on this timeline touches the DB until you save (${MOD_KEY}-drag freely)`}
              >
                {editing.saving
                  ? "Saving…"
                  : draft.dirty
                    ? `Save · ${draft.changedCount}`
                    : "Saved"}
              </Button>
            </>
          )}
          <span className="text-xs text-fg-muted">{scheduledCount} scheduled</span>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-3 bg-base p-4">
        {/* The timeline is one card — a Gantt grid has no natural row groups to
            card individually, so the surface itself carries the language. */}
        <div
          ref={scrollRef}
          className="min-w-0 flex-1 overflow-auto rounded-xl border border-subtle bg-surface shadow-lift"
        >
          {scheduledCount === 0 ? (
            <div className="p-8" {...emptyDropProps}>
              <EmptyState
                icon={GanttChartSquare}
                message={
                  filtered
                    ? "No scheduled issues match this query."
                    : canUpdate
                      ? "No scheduled issues yet — set a start and target date on an issue, or drop one here from the Unscheduled tray."
                      : "No scheduled issues yet — set a start and target date on an issue to place it on the roadmap."
                }
              />
            </div>
          ) : (
            <RoadmapTimeline
              model={model}
              visibleRows={visibleRows}
              bands={bands}
              dayWidth={dayWidth}
              labelWidth={labelWidth}
              onLabelResizeStart={startLabelResize}
              canEdit={canUpdate}
              showConnectors={showConnectors}
              collapsedEpicIds={editing.collapsedIds}
              soloIds={soloIds}
              onToggleSolo={toggleSolo}
              memberIds={memberIds}
              onToggleMember={canCurate ? onToggleMember : null}
              selectedIds={selectedIds}
              onSelectRow={selectRow}
              onRubberSelect={rubberSelect}
              scrollRef={scrollRef}
              onExtend={extendDomain}
              onToggleCollapse={editing.toggleCollapse}
              onCommitSpan={editing.commitSpan}
              canReorder={canUpdate && rankOrdered}
              onReorderRow={editing.reorderRow}
              onCreateLink={editing.beginLink}
              onEdgeClick={editing.openLinkEditor}
              onContextMenu={(row, x, y) => {
                // Right-clicking INSIDE a multi-selection targets the whole
                // selection; anywhere else falls back to the row menu.
                if (selectedIds.size > 1 && selectedIds.has(row.item.id)) {
                  setSelectionMenu({ x, y });
                } else {
                  editing.openMenu(row, x, y);
                }
              }}
              trayDragItem={trayDragItem}
              onTrayDrop={(item, dayIndex) => {
                editing.scheduleFromTray(item, dayIndex);
                setTrayDragItem(null);
              }}
              timelogByItem={timelogBatch.data}
              rollupByItem={rollupByItem}
            />
          )}
        </div>
        <UnscheduledTray
          viewId={view.id}
          query={trayQuery}
          projectId={trayProjectId}
          excludeIds={rowItemIds}
          canEdit={canUpdate}
          onDragStart={setTrayDragItem}
          onDragEnd={() => setTrayDragItem(null)}
        />
      </div>

      {editing.menu && (
        <RoadmapContextMenu
          row={editing.menu.row}
          x={editing.menu.x}
          y={editing.menu.y}
          onClose={editing.closeMenu}
          collapsed={editing.collapsedIds.has(editing.menu.row.item.id)}
          soloed={soloIds.has(editing.menu.row.item.id)}
          isMember={memberIds.has(editing.menu.row.item.id)}
          canCurate={canCurate}
          rankOrdered={rankOrdered}
          onToggleCollapse={editing.toggleCollapse}
          onToggleSolo={toggleSolo}
          onToggleMember={onToggleMember}
          onPatch={editing.applyPatches}
          onImportChildren={handleImportChildren}
          onSpreadChildren={handleSpreadChildren}
          onOrderChildren={editing.orderChildrenByDate}
          onRemoveLink={editing.deleteLink}
        />
      )}

      {selectionMenu && selectedItems.length > 0 && (
        <RoadmapSelectionMenu
          items={selectedItems}
          x={selectionMenu.x}
          y={selectionMenu.y}
          memberIds={memberIds}
          canCurate={canCurate}
          onToggleMembers={onToggleMembers}
          onPatch={editing.applyPatches}
          onDeselect={() => setSelectedIds(new Set())}
          onClose={() => setSelectionMenu(null)}
        />
      )}

      {confirmDialog}

      {editing.linkAnchor && (
        <LinkPopover
          x={editing.linkAnchor.x}
          y={editing.linkAnchor.y}
          sourceKey={editing.linkAnchor.sourceKey}
          targetKey={editing.linkAnchor.targetKey}
          currentType={editing.linkAnchor.linkType}
          onPick={editing.pickLinkType}
          onRemove={editing.linkAnchor.linkId ? editing.removeAnchorLink : undefined}
          onClose={editing.closeLinkPopover}
        />
      )}
    </div>
  );
}

/** The view's remembered day width, or the default; clamped, so a stale value
 *  from an older range never lands outside today's. */
function storedDayWidth(viewId: string): number {
  const stored = Number(window.localStorage.getItem(roadmapZoomStorageKey(viewId)));
  return Number.isFinite(stored) && stored > 0 ? clampDayWidth(stored) : ROADMAP_DAY_WIDTH;
}

const TOOLBAR_ICON_BUTTON =
  "flex h-7 items-center rounded-md border border-strong px-1.5 text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer";

/** A bordered icon-only toolbar button; `disabledClass` styles its disabled state. */
function ToolbarIconButton({
  icon: Icon,
  label,
  title,
  onClick,
  disabled,
  disabledClass,
}: {
  icon: LucideIcon;
  label: string;
  title: string;
  onClick: () => void;
  disabled?: boolean;
  disabledClass?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={title}
      className={disabledClass ? `${TOOLBAR_ICON_BUTTON} ${disabledClass}` : TOOLBAR_ICON_BUTTON}
    >
      <Icon size={13} aria-hidden />
    </button>
  );
}

/** An aria-pressed toolbar toggle, accent-filled while pressed. */
function ToolbarToggle({
  pressed,
  onClick,
  title,
  icon: Icon,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  title: string;
  icon?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={pressed}
      title={title}
      className={`${Icon ? "flex h-7 items-center gap-1" : "h-7"} rounded-md border px-2 text-xs cursor-pointer ${
        pressed
          ? "border-accent/60 bg-accent/15 text-accent-text"
          : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg"
      }`}
    >
      {Icon && <Icon size={12} aria-hidden />}
      {children}
    </button>
  );
}
