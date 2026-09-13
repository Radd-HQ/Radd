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
  Redo2,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { api } from "../../lib/api";
import { startHorizontalDrag } from "../../lib/drag";
import { useDurationConfig, useIsAuthenticated } from "../../lib/hooks";
import { projectTimeloggingQuery, timelogBatchChunkedQuery } from "../../lib/queries";
import {
  ApiPath,
  ITEMS_PAGE_LIMIT,
  ROADMAP_CHILDREN_PAGE_CAP,
  ROADMAP_DAY_WIDTH,
  ROADMAP_DAY_WIDTH_MAX,
  ROADMAP_DAY_WIDTH_MIN,
  ROADMAP_EXTEND_STEP_DAYS,
  ROADMAP_FRAME_FILL,
  ROADMAP_LABEL_MAX_WIDTH,
  ROADMAP_LABEL_MIN_WIDTH,
  ROADMAP_LABEL_WIDTH,
  roadmapLabelWidthStorageKey,
  ROADMAP_PROGRESS_STALE_MS,
  ROADMAP_ZOOM_LEVELS,
} from "../../lib/constants";
import { pushToast } from "../../lib/toast";
import { ItemKind, type Item, type Project, type View } from "../../lib/types";
import { Button } from "../Button";
import { useConfirm } from "../ConfirmDialog";
import { EmptyState } from "../EmptyState";
import { Select } from "../Select";
import { useRollupBatch } from "../items/RollupBar";
import { RoadmapTimeline } from "./RoadmapTimeline";
import { RoadmapContextMenu } from "./RoadmapContextMenu";
import { LinkPopover } from "./LinkPopover";
import { UnscheduledTray } from "./UnscheduledTray";
import { useRoadmapEditing } from "./useRoadmapEditing";
import {
  NO_EXTENSION,
  ROADMAP_ROW_H,
  RoadmapRowKind,
  autoSchedulePlan,
  buildRoadmapModel,
  durationDaysFromEstimate,
  importChildrenPlan,
  intraEpicBlocksEdges,
  parseDay,
  type RoadmapExtension,
  type RoadmapRow,
} from "./roadmap-model";
import { RoadmapSelectionMenu } from "./RoadmapSelectionMenu";
import { useRoadmapDraft } from "./useRoadmapDraft";
import { useRoadmapViewport } from "./useRoadmapViewport";
import { ExtendDirection, type ExtendDirectionValue } from "./useBarDrag";
import { MOD_KEY, modShortcut, shiftModShortcut } from "../../lib/platform";
import { todayIso } from "../../lib/dates";

export interface RoadmapSurfaceProps {
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
  /** "Show closed": false = done/canceled items are not drawn at all (RADD-946
   *  — it was a ~3-month recency window, which made the control look dead). */
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
 * Roadmap / timeline / Gantt (specs 19 + 77 + 78 + 79 + 81): dated items
 * render as bars on a week/month axis; epics are expandable rows over their
 * children. With item.update in scope the surface is a planning editor — drag
 * to move/schedule (an epic body-drag carries its scheduled children like a
 * container, dependents cascade along, Alt = just that bar), stretch edges to
 * resize, ○-drag between bars to create typed links (popover at drop),
 * click a connector to retype/remove it, right-click for the epic/leaf verbs
 * incl. estimate/assignee-aware "Auto-schedule children" and its as-is
 * counterpart "Bring children into roadmap" — otherwise it stays the
 * read-only timeline. Rows are RANK-STABLE (spec 82): the fetch order is
 * the row order, row labels drag-to-reorder among siblings (rank-ordered
 * views only), and date order is an explicit verb rather than a re-sort. The
 * domain extends a month at a time via the axis +caps or by holding a drag at
 * the pane's edge. Every gesture persists through the existing item PATCH and
 * item-links endpoints. Since spec 79 this is a VIEW surface
 * (routes/view.tsx) — mount with `key={view.id}` so zoom, extension, and the
 * collapse/tray state re-initialize per view.
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

  // Solo (focus-scheduling): with a non-empty solo set, the model is built
  // from ONLY the soloed epics + their loaded children — rows AND the time
  // domain collapse to what's being scheduled. Session-only by design: a
  // persisted solo would read as data loss on the next visit.
  // Draft wave: gestures edit a LOCAL draft; the model renders drafted items
  // and only the explicit Save writes to the DB (undo/redo in op-sized steps).
  const draft = useRoadmapDraft();
  const draftedItems = useMemo(() => draft.applyTo(items), [draft, items]);
  useEffect(() => {
    if (!draft.dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [draft.dirty]);

  const [soloIds, setSoloIds] = useState<ReadonlySet<string>>(() => new Set());
  const modelItems = useMemo(() => {
    const epicIds = new Set(
      draftedItems.filter((item) => item.kind === ItemKind.epic).map((item) => item.id),
    );
    return draftedItems.filter((item) => {
      // Epics-only mode: a non-epic renders only NESTED under its loaded
      // epic — never promoted to a standalone row. The fetch clause already
      // says this; the belt catches stranded children (e.g. the recency
      // clause dropped a done epic while its child stays recent).
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
  const model = useMemo(
    () => buildRoadmapModel(modelItems, todayIso(), extension),
    [modelItems, extension],
  );

  const editing = useRoadmapEditing(view, model, draft, items);
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
    if (ok) draft.clear();
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
  const [dayWidth, setDayWidth] = useState(ROADMAP_DAY_WIDTH);
  const [showConnectors, setShowConnectors] = useState(true);
  const [trayDragItem, setTrayDragItem] = useState<Item | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Timelog seconds (spec 78 + progress-tint polish): ONE chunked batch over
  // every loaded LEAF row id (bars tint at logged/estimate) unioned with every
  // epic's loaded children (auto-schedule durations — includes the date-less
  // ones) — fetched lazily when the project has timelogging enabled, viewers
  // included since the tints are read UI. All-projects roadmaps
  // (project null, spec 79) just attempt the batch: items span projects, and
  // failures/disabled/estimate-less projects all degrade quietly to no
  // tint/default durations (retry: false, no toast). Generous staleTime, no
  // polling — roadmaps can be huge.
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
    enabled: useIsAuthenticated() && timeloggingOn && timelogItemIds.length > 0,
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
  /** Children + their estimate batch (durations) — the two verb inputs. */
  const loadChildrenWithEstimates = useCallback(
    async (row: RoadmapRow): Promise<{ children: Item[]; durations: Map<string, number> } | null> => {
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
    [fetchEpicChildren, timeloggingOn, queryClient, durationConfig.hoursPerDay],
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
        optimistic: { ...patch },
        insert: loaded.has(itemId) ? undefined : byId.get(itemId),
      }));
    },
    [items],
  );

  const handleAutoSchedule = useCallback(
    async (row: RoadmapRow) => {
      const loaded = await loadChildrenWithEstimates(row);
      if (!loaded) return;
      const { children, durations } = loaded;
      // Auto-schedule wants a duration for EVERY child — no-estimate children
      // fall back to the plan's default length.
      const allDurations = new Map(
        children.map((child) => [
          child.id,
          durations.get(child.id) ??
            durationDaysFromEstimate(undefined, durationConfig.hoursPerDay),
        ]),
      );
      const plan = autoSchedulePlan(
        children,
        intraEpicBlocksEdges(children),
        row.item.start_date ?? todayIso(),
        allDurations,
        row.item,
      );
      editing.applyPatches(
        withInserts(plan.patches, children),
        () => {
          pushToast(`Scheduled ${plan.scheduledCount} item${plan.scheduledCount === 1 ? "" : "s"}`);
          // Spec 82: once the date unit has landed, rewrite ranks to the
          // plan's schedule order so the fresh schedule reads top-to-bottom
          // by date. Chain failure toasts on its own — the committed dates
          // stand (deliberately not part of the optimistic unit).
          editing.applyRankChain(plan.orderedIds);
        },
        `Auto-schedule ${row.item.key}'s children`,
      );
    },
    [loadChildrenWithEstimates, durationConfig.hoursPerDay, editing, withInserts],
  );

  // "Bring children into roadmap" — the AS-IS counterpart to Auto-schedule:
  // same anchor (epic start ?? today) and same duration source (timelog batch
  // + hours/day), but only children WITH an estimate enter the map — the plan
  // gives the rest its 1-day import default, and already-dated children are
  // untouched. One optimistic unit; no rank chain.
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
      editing.applyPatches(
        withInserts(plan.patches, loaded.children),
        () => pushToast(`Brought ${count} ${count === 1 ? "child" : "children"} into the roadmap`),
        `Bring ${row.item.key}'s children in`,
      );
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
  const { zoomBy } = useRoadmapViewport(scrollRef, labelWidth, dayWidth, setDayWidth);

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
    const targetW = Math.min(
      ROADMAP_DAY_WIDTH_MAX,
      Math.max(ROADMAP_DAY_WIDTH_MIN, (visible * ROADMAP_FRAME_FILL) / spanDays),
    );
    setDayWidth(targetW);
    const firstRowIndex = Math.min(
      ...rows.map((row) => visibleRows.findIndex((r) => r.item.id === row.item.id)).filter((i) => i >= 0),
    );
    requestAnimationFrame(() => {
      el.scrollLeft = Math.max(0, minStart * targetW - (visible - spanDays * targetW) / 2);
      if (Number.isFinite(firstRowIndex)) {
        // Rows start after the 40px axis header in the scroll content.
        el.scrollTop = Math.max(0, 40 + firstRowIndex * ROADMAP_ROW_H - el.clientHeight / 2);
      }
    });
  }, [scrollRef, selectedIds, model.rows, visibleRows, labelWidth]);

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
  }, [frameSelection, draft]);

  // Keep TODAY in view: the domain begins at the earliest loaded bar — often
  // years back — so an unanchored mount dropped the viewport at the oldest end
  // of history. Anchor today ~1/3 into the visible timeline, re-applied while
  // pages stream in (each page can shift the domain start, which would change
  // what a raw scrollLeft means) and on zoom, but DISENGAGED the moment the
  // user scrolls or drags the pane themselves so it never fights a human.
  // Today outside the domain clamps to the nearest end. The Today button
  // re-engages the anchor.
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
            // Ctrl+wheel / ± leave the presets — show where we landed.
            ...(ROADMAP_ZOOM_LEVELS.some((zoom) => zoom.width === dayWidth)
              ? []
              : [{ value: String(dayWidth), label: `${dayWidth.toFixed(1)}px` }]),
          ]}
        />
        <button
          type="button"
          onClick={() => zoomBy(1 / 1.4)}
          aria-label="Zoom out"
          title="Zoom out (or ctrl+wheel on the timeline)"
          className="flex h-7 items-center rounded-md border border-strong px-1.5 text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer"
        >
          <ZoomOut size={13} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => zoomBy(1.4)}
          aria-label="Zoom in"
          title="Zoom in (or ctrl+wheel on the timeline)"
          className="flex h-7 items-center rounded-md border border-strong px-1.5 text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer"
        >
          <ZoomIn size={13} aria-hidden />
        </button>
        <button
          type="button"
          onClick={scrollToToday}
          disabled={model.todayIndex === null}
          title="Scroll the today line into view"
          className="h-7 rounded-md border border-strong px-2 text-xs text-fg hover:border-emphasis hover:text-heading cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
        >
          Today
        </button>
        <button
          type="button"
          onClick={() => setShowConnectors((value) => !value)}
          aria-pressed={showConnectors}
          title="Draw dependency lines between visible bars — click one to retype or remove it. Moving a bar pushes its blocks-dependents along; moving an epic slides its scheduled children with it. Hold Alt while dropping to move just that bar — no children, no cascade."
          className={`h-7 rounded-md border px-2 text-xs cursor-pointer ${
            showConnectors
              ? "border-accent/60 bg-accent/15 text-accent-text"
              : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg"
          }`}
        >
          Dependencies
        </button>
        <button
          type="button"
          onClick={() => editing.setAllCollapsed(collapsibleEpicIds)}
          disabled={collapsibleEpicIds.length === 0}
          aria-label="Collapse all epics"
          title="Collapse all epics"
          className="flex h-7 items-center rounded-md border border-strong px-1.5 text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
        >
          <ChevronsDownUp size={13} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => editing.setAllCollapsed([])}
          disabled={editing.collapsedIds.size === 0}
          aria-label="Expand all epics"
          title="Expand all epics"
          className="flex h-7 items-center rounded-md border border-strong px-1.5 text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
        >
          <ChevronsUpDown size={13} aria-hidden />
        </button>
        {(membersCount > 0 || membersOnly) && (
          <button
            type="button"
            onClick={onToggleMembersOnly}
            aria-pressed={membersOnly}
            title={
              membersOnly
                ? "Showing only this roadmap's pinned members (and their children) — click for everything."
                : "Show only the items pinned to this roadmap."
            }
            className={`flex h-7 items-center gap-1 rounded-md border px-2 text-xs cursor-pointer ${
              membersOnly
                ? "border-accent/60 bg-accent/15 text-accent-text"
                : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg"
            }`}
          >
            <Bookmark size={12} aria-hidden />
            Members · {membersCount}
          </button>
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
        <button
          type="button"
          onClick={onToggleEpicsOnly}
          aria-pressed={epicsOnly}
          title="Drown out the noise: only epics and their scheduled children draw — standalone scheduled issues and subtasks are hidden."
          className={`flex h-7 items-center gap-1 rounded-md border px-2 text-xs cursor-pointer ${
            epicsOnly
              ? "border-accent/60 bg-accent/15 text-accent-text"
              : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg"
          }`}
        >
          <Gem size={12} aria-hidden />
          Epics only
        </button>
        <button
          type="button"
          onClick={onToggleShowClosed}
          aria-pressed={showClosed}
          title="Done and canceled items are hidden — toggle to draw finished work alongside what is live."
          className={`flex h-7 items-center gap-1 rounded-md border px-2 text-xs cursor-pointer ${
            showClosed
              ? "border-accent/60 bg-accent/15 text-accent-text"
              : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg"
          }`}
        >
          <History size={12} aria-hidden />
          Show closed
        </button>
        {truncated && (
          <span className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-fg-secondary">
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
              <button
                type="button"
                onClick={draft.undo}
                disabled={!draft.canUndo}
                aria-label="Undo"
                title={draft.undoLabel ? `Undo: ${draft.undoLabel} (${modShortcut("Z")})` : "Nothing to undo"}
                className="flex h-7 items-center rounded-md border border-strong px-1.5 text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer disabled:opacity-40 disabled:pointer-events-none"
              >
                <Undo2 size={13} aria-hidden />
              </button>
              <button
                type="button"
                onClick={draft.redo}
                disabled={!draft.canRedo}
                aria-label="Redo"
                title={draft.redoLabel ? `Redo: ${draft.redoLabel} (${shiftModShortcut("Z")})` : "Nothing to redo"}
                className="flex h-7 items-center rounded-md border border-strong px-1.5 text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer disabled:opacity-40 disabled:pointer-events-none"
              >
                <Redo2 size={13} aria-hidden />
              </button>
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
                    ? "No scheduled items match this query."
                    : canUpdate
                      ? "No scheduled items yet — set a start and target date on an item, or drop one here from the Unscheduled tray."
                      : "No scheduled items yet — set a start and target date on an item to place it on the roadmap."
                }
              />
            </div>
          ) : (
            <RoadmapTimeline
              model={model}
              visibleRows={visibleRows}
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
          onAutoSchedule={handleAutoSchedule}
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
