import { Select } from "../components/Select";
import { BACKLOG_KEY } from "../lib/view-utils";
import { usePlanningSectionSearch } from "../lib/usePlanningSectionSearch";
import { PlanningControls } from "../components/views/PlanningControls";
import { accountStorageKey } from "../lib/account-storage";
import { useGroupedItems } from "../lib/useGroupedItems";
import { DEFAULT_PLANNING, planningGroups, RESCHEDULING_KEY, type PlanningOptions, planningQueries } from "../lib/planning-query";
import { planningCountQuery, usePlanningSprints } from "../lib/usePlanningSprints";
import { PublicProjectChip } from "../components/items/ItemBadges";
import { CycleChoices } from "../components/cycles/CycleSelect";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, BookmarkPlus, CalendarClock, Download, RotateCcw, GanttChartSquare, Globe, List, ListOrdered, Pencil, Pin, SearchCode, SquareKanban, Trash2, UserRound, X } from "lucide-react";
import { Slot, SlotId, useDisabledMatches } from "@radd/plugin-sdk";
import { MissingPluginType } from "../components/shell/MissingPluginType";
import { api, errorMessage } from "../lib/api";
import { Entity, invalidateEntities } from "../lib/cache";
import {
  NEW_ITEM_HOTKEY,
  ROADMAP_EPICS_ONLY_QUERY,
  ROADMAP_MAX_AUTO_PAGES,
  ROADMAP_RECENT_CLOSED_QUERY,
  ROADMAP_STRUCTURE_QUERY,
  ROADMAP_TRAY_QUERY,
  RoutePath,
  apiViewPath,
  roadmapEpicsOnlyStorageKey,
  roadmapMembersOnlyStorageKey,
  roadmapShowClosedStorageKey, ITEMS_PAGE_SIZES } from "../lib/constants";
import { downloadCsv, itemsToCsv } from "../lib/csv";
import { useCurrentUser, useDebounced, useKeyboardShortcut, usePermissions, usePointsEnabled, useAnonymousBounce, useIsAuthenticated, useItemsPageLimit } from "../lib/hooks";
import {
  capabilitiesQuery,
  cyclesQuery,
  fieldsQuery,
  infiniteViewItemsQuery,
  itemIdsQuery,
  itemsCountQuery,
  pagedViewItemsQuery,
  projectByIdQuery,
  queryKeys,
  roadmapMembersQuery,
  statesQuery,
  useTimelogBatches,
  usersQuery,
  viewQuery as viewDefinitionQuery,
  allStatesQuery,
stateCategoriesQuery } from "../lib/queries";
import { pushToast } from "../lib/toast";
import { useReorderItem, useToggleStar, useUpdateItemInView } from "../lib/item-mutations";
import {
  bucketCreatePreset,
  bucketMovePlan,
  dragEnabledForAxis,
  type BucketCreatePreset,
  type BucketRef,
} from "../lib/axis-dnd";
import {
  FieldType,
  ItemKind,
  Permission,
  ViewAxis,
  ViewType,
  type Item,
  type View,
} from "../lib/types";
import {
  columnCatalog,
  defaultColumnsFor,
  resolveColumns,
  useColumnWidths,
} from "../lib/columns";
import { combineQueryWithFilters, composeQueryWithBar } from "../lib/slq";
import { useSlqPageFilter } from "../lib/slq-filter";

import { axisLabel, applyBucketOrder,
  groupItemsForView, type ViewGroup } from "../lib/view-utils";
import {
  DEFAULT_BOARD_SLOTS,
  DEFAULT_LIST_SLOTS,
  DEFAULT_QUEUE_SLOTS,
  defaultCardDisplay,
  useCardDisplay,
} from "../lib/card-display";
import {
  activeCardLayout,
  placedAttrSet,
  placedCustomFieldKeys,
} from "../lib/card-layout";
import { CardDesignerModal } from "../components/views/carddesigner/CardDesignerModal";
import { Button } from "../components/Button";
import { Pager } from "../components/Pager";
import { DropdownMenu } from "../components/DropdownMenu";
import { Spinner } from "../components/Spinner";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { ItemContextMenu } from "../components/items/ItemContextMenu";
import { NewItemModal } from "../components/items/NewItemModal";
import { useRollupBatch } from "../components/items/RollupBar";
import { useSlaBatch } from "../components/items/SlaChips";
import { BulkActionBar } from "../components/views/BulkActionBar";
import { BucketOrderMenu } from "../components/views/BucketOrderMenu";
import { DisplayMenu } from "../components/views/DisplayMenu";
import { QueryBar } from "../components/views/QueryBar";
import { useSavedFilters, useNavPins } from "../lib/topbar-prefs";
import {
  clearUrlState,
  clearViewDisplayState,
  hasUrlState,
  readUrlState,
  writeUrlState,
} from "../lib/url-state";
import { ViewBoard } from "../components/views/ViewBoard";
import { FLAT_GROUP_KEY, ViewList } from "../components/views/ViewList";
import { ViewModal } from "../components/views/ViewModal";
import { ViewSwimlanes } from "../components/views/ViewSwimlanes";
import { RoadmapSurface } from "../components/roadmap/RoadmapSurface";
import { QueryError } from "../components/QueryError";

/**
 * Saved-view page (specs 09/11): `/p/$projectKey/v/$viewId` and the
 * all-projects `/v/$viewId`. Items come from ONE server call composed
 * from the view's `query_string` (SLQ `q=` + scope — the server filters AND
 * orders); axis bucketing into columns/sections/swimlanes is presentation only
 * (lib/view-utils). Roadmap views (spec 79) render RoadmapSurface over the
 * same machinery, auto-fetching every page (no Load-more).
 */
export function ViewPage() {
  const { viewId = "" } = useParams({ strict: false });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const currentUser = useCurrentUser();

  const views = useQuery(viewDefinitionQuery(viewId));
  // Spec 121: a visitor who cannot see this view signs in instead (hook order:
  // this runs on every render, ahead of the early returns below).
  useAnonymousBounce(views.isError);
  const authenticated = useIsAuthenticated();
  const view = views.data;
  // A plugin-contributed view type (spec 94): rendered by the plugin's `view.type` slot instead of
  // the builtin board/list surface. The header/query bar still apply — only the surface changes.
  const { data: capsManifest } = useQuery(capabilitiesQuery);
  const isPluginView = (capsManifest?.view_types ?? []).some((t) => t.key === view?.view_type);
  const isBuiltinView =
    view != null && (Object.values(ViewType) as string[]).includes(view.view_type);
  // Neither builtin nor a currently-available plugin type → its plugin was disabled/uninstalled.
  const isMissingType = view != null && !isBuiltinView && !isPluginView && capsManifest != null;
  // The plugin is enabled but this view TYPE has been turned off (per-user/instance-wide) — its
  // `view.type` surface won't render, so show the "turned off" notice rather than a blank page.
  const disabledViewTypes = useDisabledMatches(SlotId.viewType);
  const isDisabledPluginView =
    view != null && isPluginView && disabledViewTypes.has(view.view_type);
  const projectLookup = useQuery(projectByIdQuery(view?.project_id ?? ""));
  const project = projectLookup.data ?? null;

  // Quick filters (Jira-style chips): active ones AND into the query, and the
  // whole machinery (fetch, optimistic drag/star/reorder caches) targets the
  // FILTERED dataset via this effective view. Reset when the view changes.
  const [activeFilters, setActiveFilters] = useState<Set<string>>(
    () => new Set(readUrlState().f?.split(",").filter(Boolean) ?? []),
  );
  // Re-seed from the URL on view change: a fresh navigation carries no state
  // and lands clean, a refresh or a pasted link restores what was applied.
  useEffect(() => {
    setActiveFilters(new Set(readUrlState().f?.split(",").filter(Boolean) ?? []));
  }, [viewId]);
  const toggleFilter = (name: string) => {
    setActiveFilters((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      writeUrlState({ f: next.size ? [...next].join(",") : null });
      return next;
    });
  };
  // PERSONAL saved-filter chips (top-bar redesign): the user's own SLQ chips
  // from the profile preferences — same AND-into-the-fetch semantics as the
  // view's shared quick filters, URL-synced under `pf`.
  const savedFilters = useSavedFilters();
  const navPins = useNavPins();
  const [activePersonal, setActivePersonal] = useState<Set<string>>(
    () => new Set(readUrlState().pf?.split(",").filter(Boolean) ?? []),
  );
  useEffect(() => {
    setActivePersonal(new Set(readUrlState().pf?.split(",").filter(Boolean) ?? []));
  }, [viewId]);
  const togglePersonal = (name: string) => {
    setActivePersonal((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      writeUrlState({ pf: next.size ? [...next].join(",") : null });
      return next;
    });
  };
  const resetView = () => {
    clearUrlState();
    if (viewId) clearViewDisplayState(viewId);
    setActiveFilters(new Set());
    setActivePersonal(new Set());
    slqFilter.runQuery("");
    // Display prefs are read at mount, so a reload is the honest way to show
    // the restored defaults rather than half-applying them.
    window.location.reload();
  };
  // Ad-hoc SLQ bar: since the pagination wave the COMMITTED bar
  // query COMPOSES into the fetch below like a quick filter — conditions AND
  // in, its ORDER BY replaces the view's — instead of intersecting one probe
  // page with the loaded rows (which at 503k items read as "4 cards out of
  // 1800 loaded" and silently ignored the bar's ORDER BY).
  const slqFilter = useSlqPageFilter(view?.project_id ? { project_id: view.project_id } : {});
  const effectiveView = useMemo(() => {
    if (!view) return view;
    const active = [
      ...view.quick_filters
        .filter((entry) => activeFilters.has(entry.name))
        .map((entry) => entry.query),
      ...savedFilters.filters
        .filter((entry) => activePersonal.has(entry.name))
        .map((entry) => entry.query),
    ];
    const bar = slqFilter.committed.trim();
    if (active.length === 0 && !bar) return view;
    let combined = combineQueryWithFilters(view.query, active);
    if (bar) combined = composeQueryWithBar(combined, bar);
    const params = new URLSearchParams();
    if (combined) params.set("q", combined);
    if (view.project_id) params.set("project_id", view.project_id);
    return { ...view, query: combined, query_string: params.toString() };
  }, [view, activeFilters, savedFilters.filters, activePersonal, slqFilter.committed]);

  // Roadmap perf wave: a roadmap draws epics and dated bars —
  // nothing else — so its fetch narrows to exactly that instead of streaming
  // the whole match set (fetch-all on a 100k-item project was 505 sequential
  // pages / ~200 MB). Unscheduled leaves live in the tray's own bounded query;
  // date-less children are fetched per epic when a verb needs them. The
  // default-on recency clause additionally drops closed items whose bar ended
  // more than ~3 months ago ("Show closed" in the surface toolbar lifts it,
  // persisted per view).
  const isRoadmap = view?.view_type === ViewType.roadmap;
  const isPlanning = view?.view_type === ViewType.planning;
  const planningStorage = accountStorageKey(`radd.planning:${viewId}`);
  const readPlanning = (): PlanningOptions => {
    try {
      const stored = JSON.parse(localStorage.getItem(planningStorage) ?? "{}");
      return { ...DEFAULT_PLANNING,
        showCompleted: stored.showCompleted !== false,
        backlogOrder: ["priority", "recent", "manual"].includes(stored.backlogOrder) ? stored.backlogOrder : "priority",
      };
    } catch { return {...DEFAULT_PLANNING}; }
  };
  const [planningOptions, setPlanningOptions] = useState<PlanningOptions>(readPlanning);
  useEffect(() => setPlanningOptions(readPlanning()), [planningStorage]);
  const changePlanning = (patch: Partial<PlanningOptions>) => setPlanningOptions(current => {
    const next = {...current, ...patch};
    try { localStorage.setItem(planningStorage, JSON.stringify({showCompleted: next.showCompleted, backlogOrder: next.backlogOrder})); } catch { /* session still works */ }
    return next;
  });
  const backlogSearch = useDebounced(planningOptions.search, 250);

  const [showClosed, setShowClosed] = useState(
    () => window.localStorage.getItem(roadmapShowClosedStorageKey(viewId)) === "1",
  );
  useEffect(() => {
    setShowClosed(window.localStorage.getItem(roadmapShowClosedStorageKey(viewId)) === "1");
  }, [viewId]);
  const toggleShowClosed = () => {
    setShowClosed((current) => {
      window.localStorage.setItem(roadmapShowClosedStorageKey(viewId), current ? "0" : "1");
      return !current;
    });
  };
  // "Epics only" (default off): everything scheduled draws; the toggle swaps
  // in the tighter epics-and-their-children clause to drown out the noise.
  const [epicsOnly, setEpicsOnly] = useState(
    () => window.localStorage.getItem(roadmapEpicsOnlyStorageKey(viewId)) === "1",
  );
  useEffect(() => {
    setEpicsOnly(window.localStorage.getItem(roadmapEpicsOnlyStorageKey(viewId)) === "1");
  }, [viewId]);
  const toggleEpicsOnly = () => {
    setEpicsOnly((current) => {
      window.localStorage.setItem(roadmapEpicsOnlyStorageKey(viewId), current ? "0" : "1");
      return !current;
    });
  };
  // Curated membership (roadmap wave): the member set is read through the
  // item dialect's `roadmap` field, so it arrives hydrated + RBAC-scoped.
  // Members/All: with members and no stored override, the roadmap opens
  // members-only — pinning the first item is what flips a roadmap into
  // curated mode, no configuration step.
  const members = useQuery({ ...roadmapMembersQuery(viewId), enabled: Boolean(viewId) && isRoadmap });
  const memberItems = useMemo(() => members.data ?? [], [members.data]);
  const memberIds = useMemo(() => new Set(memberItems.map((m) => m.id)), [memberItems]);
  const [membersOverride, setMembersOverride] = useState<string | null>(
    () => window.localStorage.getItem(roadmapMembersOnlyStorageKey(viewId)),
  );
  useEffect(() => {
    setMembersOverride(window.localStorage.getItem(roadmapMembersOnlyStorageKey(viewId)));
  }, [viewId]);
  const membersOnly =
    membersOverride === null ? memberItems.length > 0 : membersOverride === "1";
  const toggleMembersOnly = () => {
    const next = membersOnly ? "0" : "1";
    window.localStorage.setItem(roadmapMembersOnlyStorageKey(viewId), next);
    setMembersOverride(next);
  };
  const toggleMembers = async (itemIds: string[], makeMember: boolean) => {
    try {
      await Promise.all(
        itemIds.map((itemId) => {
          const path = `${apiViewPath(viewId)}/members/${itemId}`;
          return makeMember ? api.put<void>(path, undefined) : api.delete(path);
        }),
      );
      await invalidateEntities(queryClient, Entity.item);
    } catch {
      pushToast(makeMember ? "Couldn't add to this roadmap" : "Couldn't remove from this roadmap");
    }
  };
  const toggleMember = (itemId: string, makeMember: boolean) =>
    void toggleMembers([itemId], makeMember);
  // Members clause: exact membership via the `roadmap` field, plus the ride-
  // along — a member EPIC brings its DIRECT children through `parent IN`
  // (all the roadmap draws; `epic IN` would also match grandchildren via a
  // correlated nearest-epic walk that costs ~10x on a big project).
  const membersClause = useMemo(() => {
    if (memberItems.length === 0) return null;
    const epicKeys = memberItems
      .filter((m) => m.kind === ItemKind.epic)
      .map((m) => m.key);
    return epicKeys.length
      ? `roadmap = "${viewId}" OR parent IN (${epicKeys.join(", ")})`
      : `roadmap = "${viewId}"`;
  }, [memberItems, viewId]);
  const memberFiltering = membersOnly && membersClause !== null;
  const fetchQueryView = useMemo(() => {
    if (!effectiveView || !isRoadmap) return effectiveView;
    const combined = combineQueryWithFilters(effectiveView.query, [
      epicsOnly ? ROADMAP_EPICS_ONLY_QUERY : ROADMAP_STRUCTURE_QUERY,
      ...(showClosed ? [] : [ROADMAP_RECENT_CLOSED_QUERY]),
      ...(memberFiltering && membersClause ? [membersClause] : []),
    ]);
    const params = new URLSearchParams();
    params.set("q", combined);
    if (effectiveView.project_id) params.set("project_id", effectiveView.project_id);
    return { ...effectiveView, query: combined, query_string: params.toString() };
  }, [effectiveView, isRoadmap, showClosed, epicsOnly, memberFiltering, membersClause]);

  const columnAxis =
    view?.view_type === ViewType.planning
      ? ViewAxis.cycle
      : view?.view_type === ViewType.queue
        ? null
        : (view?.group_by ?? (view?.view_type === ViewType.board ? ViewAxis.state : null));
  const laneAxis = view?.view_type === ViewType.board ? view.swimlane_by : null;
  const isGrouped = Boolean(view && !isPlanning && !isRoadmap && view.view_type !== ViewType.queue && columnAxis);
  const cycles = useQuery({ ...cyclesQuery(), enabled: Boolean(view) && (
    view?.view_type === ViewType.planning || view?.group_by === ViewAxis.cycle || view?.swimlane_by === ViewAxis.cycle
  ) });
  const planning = useMemo(() => planningQueries(fetchQueryView, cycles.data, {...planningOptions, search: backlogSearch}), [fetchQueryView, cycles.data, planningOptions, backlogSearch]);
  const groupedItems = useGroupedItems(fetchQueryView, columnAxis, laneAxis, cycles.data, isGrouped && (!(columnAxis === "cycle" || laneAxis === "cycle") || cycles.isSuccess));
  const pagedFetchView = isPlanning ? planning.backlog : fetchQueryView;
  const sprintItems = usePlanningSprints(planning.sprints, isPlanning && cycles.isSuccess && planning.cycleCount > 0);
  const recoveryItems = usePlanningSprints(planning.recovery, isPlanning && cycles.isSuccess, 1);
  const historyItems = usePlanningSprints(planning.history, isPlanning && planningOptions.history && Boolean(planning.historyId), 1);
  const sectionSearch = usePlanningSectionSearch(planning, isPlanning && cycles.isSuccess, accountStorageKey(`planning-search:${viewId}`), planningOptions.history);
  const openSprintCount = useQuery({
    ...planningCountQuery(planning.sprintOpen),
    enabled: isPlanning && cycles.isSuccess && planning.cycleCount > 0,
  });

  // Roadmaps auto-stream their whole (narrowed) match set below; every OTHER
  // view type pages its result (Planning pages only its backlog) CLASSICALLY since the pagination wave — one page at a
  // time behind a first/prev/numbers/next/last Pager, page carried in the URL.
  const itemPages = useInfiniteQuery({
    ...infiniteViewItemsQuery(fetchQueryView),
    enabled: Boolean(view) && isRoadmap,
  });
  const [page, setPageState] = useState(() => Math.max(1, Number(readUrlState().pg) || 1));
  useEffect(() => {
    setPageState(Math.max(1, Number(readUrlState().pg) || 1));
  }, [viewId]);
  const setPage = (next: number) => {
    setPageState(next);
    writeUrlState({ pg: next > 1 ? String(next) : null });
  };
  // A changed query invalidates the page NUMBER (page 7 of the old result set
  // means nothing in the new one) — snap back to 1, but never on mount.
  const pageQueryString = pagedFetchView?.query_string ?? "";
  const prevPageQsRef = useRef(pageQueryString);
  useEffect(() => {
    if (prevPageQsRef.current !== pageQueryString) {
      prevPageQsRef.current = pageQueryString;
      setPageState(1);
      writeUrlState({ pg: null });
    }
  }, [pageQueryString]);
  // RADD-1154: 50 per page on a phone, 200 otherwise.
  const [pageLimit, setPageLimit] = useItemsPageLimit();
  const pagedItems = useQuery({
    ...pagedViewItemsQuery(pagedFetchView, page, pageLimit),
    enabled: Boolean(view) && !isRoadmap && !isGrouped,
  });
  const ordinaryItemsTotal = useQuery({
    // The spec-75 count endpoint: same filter surface + visibility as the list.
    ...itemsCountQuery(
      pagedFetchView?.project_id ? { project_id: pagedFetchView.project_id } : {},
      pagedFetchView?.query ?? "",
    ),
    enabled: Boolean(view) && !isRoadmap && !isGrouped && !isPlanning,
  });
  const planningItemsTotal = useQuery({ ...planningCountQuery(planning.backlog), enabled: isPlanning });
  const itemsTotal = isPlanning ? planningItemsTotal : ordinaryItemsTotal;
  const totalCount = itemsTotal.data?.total ?? null;
  const pageCount =
    totalCount === null ? null : Math.max(1, Math.ceil(totalCount / pageLimit));
  useEffect(() => {
    if (isPlanning && pageCount !== null && page > pageCount && !itemsTotal.isFetching) setPage(pageCount);
  }, [isPlanning, pageCount, page, itemsTotal.isFetching]);
  // Roadmap views auto-stream their (narrowed) match set — but in CAPPED
  // bursts, so a broad query can never re-create fetch-all: after
  // ROADMAP_MAX_AUTO_PAGES pages the stream pauses with a toolbar notice
  // whose "load more" arms another burst.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = itemPages;
  const [roadmapAutoCap, setRoadmapAutoCap] = useState(ROADMAP_MAX_AUTO_PAGES);
  useEffect(() => setRoadmapAutoCap(ROADMAP_MAX_AUTO_PAGES), [viewId]);
  const loadedPages = itemPages.data?.pages.length ?? 0;
  useEffect(() => {
    if (isRoadmap && hasNextPage && !isFetchingNextPage && loadedPages < roadmapAutoCap) {
      void fetchNextPage();
    }
  }, [isRoadmap, hasNextPage, isFetchingNextPage, fetchNextPage, loadedPages, roadmapAutoCap]);
  const roadmapTruncated = isRoadmap && Boolean(hasNextPage) && loadedPages >= roadmapAutoCap;
  // The tray's base SLQ: the view's query (+ quick filters) narrowed to the
  // open unscheduled pool — the tray pages/searches it itself.
  const roadmapTrayQuery = useMemo(
    () =>
      isRoadmap && effectiveView
        ? combineQueryWithFilters(effectiveView.query, [
            ROADMAP_TRAY_QUERY,
            // Members mode narrows the tray to the curated pool too: the
            // unscheduled members + the unscheduled children of member epics
            // — exactly what's left to schedule on THIS roadmap.
            ...(memberFiltering && membersClause ? [membersClause] : []),
          ])
        : "",
    [isRoadmap, effectiveView, memberFiltering, membersClause],
  );
  const roadmapFlat = useMemo(() => itemPages.data?.pages.flat(), [itemPages.data]);
  const items = {
    data: isGrouped ? groupedItems.items : isRoadmap ? roadmapFlat : isPlanning ? sectionSearch.displayItems([
      ...planning.scheduled.filter(g => !view?.hidden_columns?.includes(g.key)).map(g => ({key: g.key, items: sprintItems.items.filter(i => i.cycle?.id === g.key)})),
      {key: RESCHEDULING_KEY, items: recoveryItems.items},
      {key: BACKLOG_KEY, items: pagedItems.data ?? []},
      ...(planningOptions.history && planning.historyId ? [{key: `history:${planning.historyId}`, items: historyItems.items}] : []),
    ]) : pagedItems.data,
    isPending: isPlanning ? false : isGrouped ? groupedItems.isPending && !cycles.isError : isRoadmap ? itemPages.isPending : pagedItems.isPending,
    isError: isPlanning ? false : isGrouped ? (groupedItems.isError && !groupedItems.data) || ((columnAxis === "cycle" || laneAxis === "cycle") && cycles.isError) : isRoadmap ? itemPages.isError : pagedItems.isError,
    error: isGrouped ? groupedItems.error ?? cycles.error : isRoadmap ? itemPages.error : pagedItems.error ?? (isPlanning ? cycles.error ?? recoveryItems.error ?? sprintItems.error : null),
  };
  // Since the pagination wave the bar COMPOSES into the fetch (see
  // effectiveView above) — the loaded page already IS the filtered page.
  const pageItems = useMemo(() => [...new Map((items.data ?? []).map(item => [item.id, item])).values()], [items.data]);

  // Queue views (spec 64): a fixed-column triage list — axes ignored, SLA
  // chips always on, and (without an explicit ORDER BY in the SLQ) the loaded
  // server orders the complete match set by live SLA urgency before paging.
  const isQueue = view?.view_type === ViewType.queue;
  const isBoard = view?.view_type === ViewType.board;
  // Per-view card display (slots/labels/scale) — persisted under the view's id.
  // Queues use the FIXED queue column set instead (no DisplayMenu, spec 64).
  const cardDisplay = useCardDisplay(
    `view:${viewId}`,
    isBoard ? DEFAULT_BOARD_SLOTS : DEFAULT_LIST_SLOTS,
  );
  const display = isQueue ? defaultCardDisplay(DEFAULT_QUEUE_SLOTS) : cardDisplay.display;
  // Table columns (spec 108), list-type surfaces only (boards keep chip slots):
  // the SET comes from the saved view (shared), widths from localStorage
  // (personal). `fields` also feeds the axis pickers further down.
  const fields = useQuery(fieldsQuery());
  const listColumnIds = useMemo(
    () => view?.columns ?? [...defaultColumnsFor(view?.view_type)],
    [view?.columns, view?.view_type],
  );
  const fullColumnCatalog = useMemo(
    () => columnCatalog(fields.data ?? [], view?.project_id ?? null),
    [fields.data, view?.project_id],
  );
  const listColumns = useMemo(
    () => resolveColumns(listColumnIds, fullColumnCatalog),
    [listColumnIds, fullColumnCatalog],
  );
  const colWidths = useColumnWidths(viewId);
  const hasListColumn = (id: string) =>
    !isBoard && !isRoadmap && listColumns.some((column) => column.id === id);
  // Board-card layout (spec 109): the SET comes from the saved view (shared,
  // edit-gated — the columns idiom); the personal zoom scale stays local.
  const cardLayout = useMemo(() => activeCardLayout(view), [view]);
  const placedAttrs = useMemo(() => placedAttrSet(cardLayout), [cardLayout]);
  const hasCardAttr = (id: string) => isBoard && placedAttrs.has(id);
  // Field defs for `cf.<key>` card cells (types + labels).
  const cfByKey = useMemo(
    () => new Map((fields.data ?? []).map((field) => [field.key, field])),
    [fields.data],
  );
  // Custom user-field cells render names — fetch the directory only while
  // such a column (list) or placed cell (board) is actually visible.
  const needsCfUsers = isBoard
    ? placedCustomFieldKeys(cardLayout).some(
        (key) => cfByKey.get(key)?.type === FieldType.user,
      )
    : !isRoadmap && listColumns.some((column) => column.cf?.type === FieldType.user);
  const cfUsers = useQuery({ ...usersQuery, enabled: needsCfUsers });
  const usersById = useMemo(
    () =>
      needsCfUsers
        ? new Map((cfUsers.data ?? []).map((user) => [user.id, user.name]))
        : undefined,
    [needsCfUsers, cfUsers.data],
  );
  // SLA chips (spec 63): one batch call for the page's items (ids capped in
  // slaBatchQuery) — fetched while the sla slot/column is on, ALWAYS for queues.
  const pageItemIds = useMemo(() => pageItems.map((item) => item.id), [pageItems]);
  const slaByItem = useSlaBatch(
    pageItemIds,
    !isRoadmap && (isQueue || hasCardAttr("sla") || hasListColumn("sla")),
  );
  // Epic progress (spec 76): one rollup batch for the page's EPIC-kind items —
  // fetched only while the progress slot/column is on and epics are visible.
  const epicIds = useMemo(
    () => pageItems.filter((item) => item.kind === ItemKind.epic).map((item) => item.id),
    [pageItems],
  );
  // Roadmaps draw bars, not cards — no SLA/rollup batches over the full fetch.
  const rollupByItem = useRollupBatch(
    epicIds,
    !isRoadmap && (hasCardAttr("progress") || hasListColumn("progress")),
  );
  // Logged time on cards: one chunked batch over the page's items while the
  // slot/column is on. Quiet-degrade (retry: false in the query) — cards just
  // omit the readout when timelogging is off or the batch fails.
  const timelogByItem = useTimelogBatches(pageItemIds,
    authenticated && !isRoadmap && (hasCardAttr("logged_time") || hasListColumn("logged_time")));

  // The server's order stands when the view's SLQ sorts explicitly; otherwise
  // queues default to breached-first → ascending due_at → oldest created.
  const orderedItems = pageItems;
  const states = useQuery({
    ...statesQuery(view?.project_id ?? ""),
    enabled: Boolean(view?.project_id),
  });
  // All-projects views: every readable project's states, so a drop on a
  // name-keyed state column can resolve in the dragged item's own project.
  const allStates = useQuery({
    ...allStatesQuery(),
    enabled: Boolean(view) && !view?.project_id,
  });
  // Story points (spec 70): resolved per project (all-projects views fall
  // back to the instance default) — drives the board columns' Σ pts header.
  const pointsEnabled = usePointsEnabled(view?.project_id ?? undefined);

  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  // New-item affordance on project-scoped views (the old builtin board/list
  // pages carried this; views ARE the surfaces now). `c` = create.
  const canCreate = Boolean(project) && perms.project(project, Permission.itemCreate);
  // Board quick-add (spec-24 axis semantics, reversed): the + / "Add issue"
  // affordances seed the modal with the column's bucket value. Cleared on
  // every other entry path so a plain "New item" never inherits a column.
  const [createInitial, setCreateInitial] = useState<BucketCreatePreset | undefined>();
  const openCreate = useCallback((initial?: BucketCreatePreset) => {
    setCreateInitial(initial);
    setCreating(true);
  }, []);
  useKeyboardShortcut(
    NEW_ITEM_HOTKEY,
    useCallback(() => {
      if (canCreate) openCreate();
    }, [canCreate, openCreate]),
  );
  const [cycleTarget, setCycleTarget] = useState<Item | null>(null);
  const [menu, setMenu] = useState<{ item: Item; x: number; y: number } | null>(null);
  const openContextMenu = (item: Item, event: ReactMouseEvent) =>
    setMenu({ item, x: event.clientX, y: event.clientY });

  // Multi-select (list views): selection resets whenever the view changes.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<string | null>(null);
  useEffect(() => {
    setSelected(new Set());
    setAnchor(null);
  }, [view?.id, sectionSearch.signature]);

  // Soft WIP limits (spec 76): the column-header ⋯ menu PATCHes the full map
  // (delete-key to clear one column; an emptied map clears the column).
  const updateWipLimits = useMutation({
    mutationFn: (wipLimits: Record<string, number> | null) =>
      api.patch<View>(apiViewPath(viewId), { wip_limits: wipLimits }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.views }),
  });
  // Table columns (spec 108): the SET is part of the view — edit-gated PATCH.
  const updateColumns = useMutation({
    mutationFn: (columnIds: string[]) =>
      api.patch<View>(apiViewPath(viewId), { columns: columnIds }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.views }),
  });
  // RADD-855: per-view bucket order — a shared view property, edit-gated.
  const updateBucketOrder = useMutation({
    mutationFn: (body: {
      column_order?: string[];
      swimlane_order?: string[];
      hidden_columns?: string[] | null;
      collapse_empty_columns?: boolean;
    }) =>
      api.patch<View>(apiViewPath(viewId), body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.views }),
  });
  // Card layout (spec 109): same idiom — null = back to the default card.
  const updateCardLayout = useMutation({
    mutationFn: (layout: View["card_layout"]) =>
      api.patch<View>(apiViewPath(viewId), { card_layout: layout }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.views }),
  });
  const [designingCard, setDesigningCard] = useState(false);
  const setWipLimit = (bucketKey: string, limit: number | null) => {
    const next = { ...(view?.wip_limits ?? {}) };
    if (limit === null) delete next[bucketKey];
    else next[bucketKey] = limit;
    updateWipLimits.mutate(Object.keys(next).length > 0 ? next : null);
  };

  const deleteView = useMutation({
    mutationFn: (target: View) => api.delete<void>(apiViewPath(target.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.views });
      if (project) {
        void navigate({ to: RoutePath.project, params: { projectKey: project.key } });
      } else {
        void navigate({ to: RoutePath.home });
      }
    },
  });

  // A board without columns is still a board — fall back to state columns.
  // A PLANNING view is always cycle-grouped, a QUEUE is always a flat triage
  // list (both ignore their stored axes).


  const stateCategories = useQuery({
    ...stateCategoriesQuery(),
    // RADD-854: only fetched when an axis groups by the category tier.
    enabled:
      view?.group_by === ViewAxis.stateCategory || view?.swimlane_by === ViewAxis.stateCategory,
  });
  const axisContext = useMemo(
    () => ({
      states: states.data,
      allStates: allStates.data,
      stateCategories: stateCategories.data,
      fields: fields.data,
      cycles: cycles.data,
      cycleFilter: view?.cycle_filter,
    }),
    [states.data, allStates.data, stateCategories.data, fields.data, cycles.data, view?.cycle_filter],
  );
  // A cycle-grouped view shows every (matching) cycle as a header — including
  // empty staging cycles — so it renders even when the SLQ matched no items.
  const cycleGrouped = columnAxis === ViewAxis.cycle || laneAxis === ViewAxis.cycle;

  const columns: ViewGroup[] = useMemo(() => {
    if (!view) return [];
    if (!columnAxis) return [{ key: FLAT_GROUP_KEY, label: "All items", items: orderedItems }];
    if (isPlanning) return planningGroups(planning, sprintItems.items, recoveryItems.items,
      pagedItems.data ?? [], historyItems.items, cycles.data, planningOptions,
      Boolean(fetchQueryView?.query.trim()), recoveryItems.total, totalCount ?? undefined,
      historyItems.total, Boolean(sprintItems.more)).map(group => {
        const query = group.key === BACKLOG_KEY ? pagedItems : group.key === RESCHEDULING_KEY ? recoveryItems : group.key.startsWith("history:") ? historyItems : sprintItems;
        return {...group, emptyMessage: query.isPending || query.isError ? undefined : group.emptyMessage};
      });

    // RADD-855: the view's own bucket order, over the axis's natural order.
    return applyBucketOrder(
      groupItemsForView(orderedItems, columnAxis, axisContext).map(g => ({...g,total:isGrouped ? groupedItems.first?.column_totals[g.key] ?? 0 : undefined, totalPoints:isGrouped ? groupedItems.first?.column_points?.[g.key] : undefined})),
      view.column_order,
    );
  }, [view, orderedItems, columnAxis, axisContext, isGrouped, groupedItems.first, isPlanning, planning, sprintItems.items, recoveryItems.items, pagedItems.data, historyItems.items, cycles.data, planningOptions, fetchQueryView, recoveryItems.total, totalCount, historyItems.total, sprintItems.more, pagedItems.isPending, pagedItems.isError, recoveryItems.isPending, recoveryItems.isError, historyItems.isPending, historyItems.isError, sprintItems.isPending, sprintItems.isError]);
  // RADD-1175: presence. `columns` stays the FULL set (the Order menu must be
  // able to bring a hidden one back); the surfaces get the visible subset.
  const hiddenKeys = useMemo(() => new Set(view?.hidden_columns ?? []), [view?.hidden_columns]);
  const visibleColumns = useMemo(
    () => (hiddenKeys.size ? columns.filter((column) => (isPlanning && !column.cycleId) || !hiddenKeys.has(column.key)) : columns),
    [columns, hiddenKeys, isPlanning],
  );
  const collapseEmpty = Boolean(view?.collapse_empty_columns);
  const lanes: ViewGroup[] = useMemo(
    () =>
      view && laneAxis
        ? applyBucketOrder(
            groupItemsForView(orderedItems, laneAxis, axisContext).map(g => ({...g,total:isGrouped ? groupedItems.first?.lane_totals[g.key] ?? 0 : undefined})),
            view.swimlane_order,
          )
        : [],
    [view, orderedItems, laneAxis, axisContext, isGrouped, groupedItems.first],
  );

  // Cross-bucket drag (spec 24): dropping an item on a bucket sets the field the
  // grouping axis represents. Gated on item.update in the view's scope + an axis
  // that maps to a mutable field (kind is create-only). All-projects state
  // buckets are name-keyed and resolve per dragged item via allStates.
  const move = useUpdateItemInView(effectiveView);
  const starMutation = useToggleStar(effectiveView);
  const reorderMutation = useReorderItem(effectiveView);
  const onStar = (item: Item, star: boolean) => starMutation.mutate({ itemId: item.id, star });
  const onReorder = (item: Item, afterId: string | null, beforeId: string | null) =>
    reorderMutation.mutate({ itemId: item.id, afterId, beforeId });
  // Manual drag-to-rank is on when the view is in rank order — i.e. it has no
  // explicit sort (rank is the default) or explicitly `ORDER BY rank`. A view
  // sorted by another field can't be hand-reordered (the sort would fight it).
  // Shared by list rows AND the roadmap's row-label reorder (spec 82).
  const viewQuery = (isPlanning ? planning.backlog?.query : view?.query) ?? "";
  const rankOrdered =
    !/\border\s+by\b/i.test(viewQuery) || /\border\s+by\s+rank\b/i.test(viewQuery);
  const projectScoped = Boolean(view?.project_id);
  // An ALL-PROJECTS view has no single project to resolve against. It asked the
  // GLOBAL atom, which a project-scoped grant never satisfies (RADD-788), so
  // drag-to-rank was dead on every cross-project view for ordinary members.
  // "Holds it somewhere" is the honest client-side bar; the server re-checks the
  // item's own project on every reorder.
  const canUpdate = projectScoped
    ? Boolean(project) && perms.project(project, Permission.itemUpdate)
    : perms.anyProject(Permission.itemUpdate);
  const dndCtx = useMemo(
    () => ({
      projectScoped,
      states: projectScoped ? states.data : allStates.data,
      cycles: cycles.data,
    }),
    [projectScoped, states.data, allStates.data, cycles.data],
  );
  const columnDraggable = canUpdate && dragEnabledForAxis(columnAxis);
  const laneDraggable = canUpdate && dragEnabledForAxis(laneAxis);
  // WIP limits apply to state-axis columns only; the ⋯ editor additionally
  // needs edit rights and a PROJECT scope (all-projects state buckets
  // are name-keyed, so id-keyed limits can't address them).
  const stateColumns = columnAxis === ViewAxis.state;
  const canSetWipLimit = stateColumns && projectScoped && Boolean(view?.can_edit);

  const moveToBucket = (item: Item, bucket: BucketRef) => {
    if (!columnAxis || (isPlanning && (bucket.key === RESCHEDULING_KEY || bucket.key.startsWith("history:")))) return;
    const plan = bucketMovePlan(item, columnAxis, bucket, dndCtx);
    if (plan) {
      move.mutate({ itemId: item.id, patch: plan.patch, optimistic: plan.optimistic });
    } else if (
      columnAxis === ViewAxis.state &&
      !projectScoped &&
      item.state.name !== bucket.key
    ) {
      // Name-keyed drop that couldn't resolve: the item's project has no state
      // of that name — say so instead of silently snapping the card back.
      pushToast(`${item.key.split("-")[0]} has no "${bucket.label}" state`);
    }
  };
  const moveToCell = (item: Item, column: BucketRef, lane: BucketRef) => {
    const columnPlan = columnAxis ? bucketMovePlan(item, columnAxis, column, dndCtx) : null;
    const lanePlan = laneAxis ? bucketMovePlan(item, laneAxis, lane, dndCtx) : null;
    const patch = { ...columnPlan?.patch, ...lanePlan?.patch };
    if (Object.keys(patch).length === 0) return;
    move.mutate({
      itemId: item.id,
      patch,
      optimistic: { ...columnPlan?.optimistic, ...lanePlan?.optimistic },
    });
  };

  // Multi-select toggle: plain click toggles + sets the range anchor; shift-click
  // selects the range from the anchor in the current render order.
  const orderedIds = (isPlanning ? sectionSearch.apply(visibleColumns) : columns).flatMap(g => g.items.map(i => i.id));
  const onSelectToggle = (item: Item, event: ReactMouseEvent) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (event.shiftKey && anchor) {
        const a = orderedIds.indexOf(anchor);
        const b = orderedIds.indexOf(item.id);
        if (a !== -1 && b !== -1) {
          const [lo, hi] = a < b ? [a, b] : [b, a];
          for (let i = lo; i <= hi; i++) next.add(orderedIds[i]);
        }
      } else if (next.has(item.id)) {
        next.delete(item.id);
      } else {
        next.add(item.id);
      }
      return next;
    });
    if (!event.shiftKey) setAnchor(item.id);
  };

  // "Select all N matching" (spec 68): the view's true match count via
  // GET /items/ids — fetched lazily once a selection exists. The ad-hoc bar
  // now composes into the fetch query, so select-all means exactly what the
  // page shows even while the bar is active (pagination wave).
  const matchingIds = useQuery({
    ...itemIdsQuery(effectiveView?.query_string ?? ""),
    enabled: Boolean(view) && selected.size > 0 && !isPlanning && !isGrouped,
  });
  const matching = !isPlanning && !isGrouped && matchingIds.data
    ? {
        total: matchingIds.data.total,
        pending: matchingIds.isFetching,
        onSelectAll: () => setSelected(new Set(matchingIds.data.ids)),
      }
    : undefined;

  if (views.isPending || (Boolean(view?.project_id) && projectLookup.isPending)) {
    return <Spinner label="Loading view…" />;
  }
  if (views.isError) {
    return (
      <div className="p-10">
        <QueryError label="views" error={views.error} />
      </div>
    );
  }
  if (!view) {
    return <div className="p-10 text-sm text-fg-muted">View not found.</div>;
  }

  // Spec 57: capabilities come from the server (owner / share level / legacy
  // atoms) — the client never re-derives team membership.
  const canEditView = view.can_edit;
  const canManageView = view.can_manage;
  const TypeIcon =
    view.view_type === ViewType.board
      ? SquareKanban
      : view.view_type === ViewType.planning
        ? CalendarClock
        : isRoadmap
          ? GanttChartSquare
          : isQueue
            ? ListOrdered
            : List;
  // Multi-select + bulk (spec 68): every surface incl. boards, gated on
  // item.update in scope.
  const selectable = canUpdate;

  const axisSummary = [
    // Queues (spec 64) and roadmaps (spec 79) ignore their stored axes — don't
    // announce them.
    view.group_by && !isQueue && !isRoadmap
      ? `Group: ${axisLabel(view.group_by, fields.data)}`
      : null,
    laneAxis ? `Swimlanes: ${axisLabel(laneAxis, fields.data)}` : null,
    cycleGrouped && view.cycle_filter ? `Cycle filter: ${view.cycle_filter}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex h-full flex-col">
      {/* The view's LIVE query bar rides in the global top bar (the reference
          design's central bar) — one input, SLQ ⟷ Ask via the mode toggle. */}
      <TopBarQuery>
        <QueryBar filter={slqFilter} projectId={view.project_id ?? undefined} />
      </TopBarQuery>

      {/* ONE header row (was two bands): identity, the SAVED chips, then
          count/knobs at the right edge. The old second band's project tabs
          (a one-item "Reports" nav) moved into the ⋯ menu — nav lives in the
          sidebar/top bar, not repeated per page. */}
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-subtle px-5 py-2">
        <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg">
          {project ? project.key : "All projects"}
        </span>
        {project?.public && <PublicProjectChip />}
        <TypeIcon size={15} className="text-fg-muted" aria-hidden />
        <h1 className="text-sm font-semibold text-heading">{view.name}</h1>
        {/* Sharing state as an icon, not a labeled chip — metadata, not headline. */}
        <span
          title={view.shared ? "Shared view" : "Personal view"}
          className={view.shared ? "text-accent-text" : "text-fg-faint"}
        >
          {view.shared ? <Globe size={12} aria-hidden /> : <UserRound size={12} aria-hidden />}
        </span>
        {/* Pin to the top bar (per-user favorites, lib/topbar-prefs). */}
        <button
          type="button"
          onClick={() => navPins.toggle({ kind: "view", id: view.id })}
          aria-pressed={navPins.isPinned(view.id)}
          title={navPins.isPinned(view.id) ? "Unpin from top bar" : "Pin to top bar"}
          className={
            "cursor-pointer rounded p-1 hover:bg-elevated focus-visible:outline-2 focus-visible:outline-focus " +
            (navPins.isPinned(view.id) ? "text-accent-text" : "text-fg-faint hover:text-fg")
          }
        >
          <Pin size={13} fill={navPins.isPinned(view.id) ? "currentColor" : "none"} aria-hidden />
        </button>
        {view.owner && view.owner.id !== currentUser?.id && (
          <span className="text-xs text-fg-muted" title="View owner">
            by {view.owner.name}
          </span>
        )}
        {/* The view's STORED query, compact (the ad-hoc filter lives up top). */}
        {(view.query ?? "").trim() !== "" && (
          <span
            title={view.query}
            className="inline-flex min-w-0 items-center gap-1 rounded border border-subtle bg-surface px-1.5 py-px text-[11px] text-fg-muted"
          >
            <SearchCode size={11} aria-hidden className="shrink-0" />
            <code className="max-w-48 truncate font-mono">{view.query}</code>
          </span>
        )}

        {/* SAVED chips — the view's shared quick filters plus the user's
            personal saved filters (moved up from the old second band). */}
        {(view.quick_filters.length > 0 || savedFilters.filters.length > 0) && (
          <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-faint">
            Saved
          </span>
        )}
        {view.quick_filters.map((filter) => {
          const active = activeFilters.has(filter.name);
          return (
            <button
              key={filter.name}
              type="button"
              aria-pressed={active}
              title={filter.query}
              onClick={() => toggleFilter(filter.name)}
              className={
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors cursor-pointer " +
                (active
                  ? "border-accent-hover bg-accent/15 text-accent-text-strong"
                  : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg")
              }
            >
              {filter.name}
            </button>
          );
        })}
        {savedFilters.filters.map((filter) => {
          const active = activePersonal.has(filter.name);
          return (
            <span key={filter.name} className="group/pfchip relative inline-flex">
              <button
                type="button"
                aria-pressed={active}
                title={filter.query}
                onClick={() => togglePersonal(filter.name)}
                className={
                  "rounded-full border px-2.5 py-0.5 pr-5 text-xs transition-colors cursor-pointer " +
                  (active
                    ? "border-accent-hover bg-accent/15 text-accent-text-strong"
                    : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg")
                }
              >
                {filter.name}
              </button>
              <button
                type="button"
                aria-label={`Delete saved filter ${filter.name}`}
                title="Delete saved filter"
                onClick={() => {
                  savedFilters.remove(filter.name);
                  if (active) togglePersonal(filter.name);
                }}
                className="absolute right-1 top-1/2 -translate-y-1/2 rounded-full p-px text-fg-faint opacity-0 transition-opacity hover:text-red-400 group-hover/pfchip:opacity-100 cursor-pointer"
              >
                <X size={10} aria-hidden />
              </button>
            </span>
          );
        })}
        {slqFilter.active && (
          <SaveFilterButton
            onSave={(name) => {
              const query = (slqFilter.probe.query ?? slqFilter.draft).trim();
              if (!query) return;
              savedFilters.save({ name, query });
              // The chip takes over from the ad-hoc bar: activate it, clear q.
              togglePersonal(name);
              slqFilter.runQuery("");
            }}
          />
        )}
        {(activeFilters.size > 0 || activePersonal.size > 0) && (
          <button
            type="button"
            onClick={() => {
              setActiveFilters(new Set());
              setActivePersonal(new Set());
              writeUrlState({ f: null, pf: null });
            }}
            className="text-xs text-fg-muted hover:text-fg cursor-pointer"
          >
            Clear
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-fg-faint">
            {isGrouped
              ? `${groupedItems.items.length.toLocaleString()} loaded · ${Object.values(groupedItems.first?.column_totals ?? {}).reduce((a,b)=>a+b,0).toLocaleString()} matching items`
              : isPlanning
              ? `${planning.cycleCount ? openSprintCount.data?.total.toLocaleString() ?? "…" : "0"} open sprint issues · ${totalCount?.toLocaleString() ?? "…"} backlog · ${recoveryItems.total?.toLocaleString() ?? "…"} need rescheduling`
              : isRoadmap
              ? // Roadmap auto-stream (spec 79): the count ticks while pages load.
                `${pageItems.length} items${itemPages.hasNextPage ? "…" : ""}`
              : totalCount !== null
                ? `${totalCount.toLocaleString()} items`
                : `${pageItems.length} items`}
          </span>
          {axisSummary && <span className="text-xs text-fg-muted">{axisSummary}</span>}
          {/* Plugin-contributed view header items (spec 94): a plugin attached to a view gets the
              view + its loaded, permission-scoped items — it can compute over exactly what the user
              can see. */}
          <Slot id={SlotId.viewHeader} view={view} items={items.data ?? []} />
          {/* Queues have a fixed column set (spec 64) and roadmaps their own
              knobs (spec 79) — no display config for either. */}
          {(hasUrlState() || activeFilters.size > 0 || slqFilter.draft !== "") && (
            <Button
              variant="ghost"
              size="sm"
              onClick={resetView}
              title="Clear the ad-hoc query, quick filters and this view's saved display settings"
            >
              <RotateCcw size={12} aria-hidden />
              Reset view
            </Button>
          )}
          {!isPlanning && !isQueue && !isRoadmap && Boolean(view?.can_edit) && columnAxis && (
            <BucketOrderMenu
              columns={columns}
              lanes={laneAxis ? lanes : []}
              onReorderColumns={(keys) => updateBucketOrder.mutate({ column_order: keys })}
              onReorderLanes={(keys) => updateBucketOrder.mutate({ swimlane_order: keys })}
              hiddenKeys={hiddenKeys}
              onToggleHidden={(key) => {
                const next = new Set(hiddenKeys);
                if (next.has(key)) next.delete(key);
                else next.add(key);
                updateBucketOrder.mutate({ hidden_columns: next.size ? [...next] : null });
              }}
              collapseEmpty={collapseEmpty}
              onSetCollapseEmpty={(value) => updateBucketOrder.mutate({ collapse_empty_columns: value })}
            />
          )}
          {!isQueue && !isRoadmap && (
            <DisplayMenu
              state={cardDisplay}
              viewOptions={isPlanning ? <PlanningControls options={planningOptions} onChange={changePlanning} plan={planning}
                hidden={hiddenKeys} canEdit={Boolean(view.can_edit)} saving={updateBucketOrder.isPending}
                onHide={id => updateBucketOrder.mutate({hidden_columns: [...hiddenKeys, id]})}
                onRestore={() => updateBucketOrder.mutate({hidden_columns: [...hiddenKeys].filter(id => !planning.scheduled.some(g => g.key === id))})}
                filtered={Boolean(fetchQueryView?.query.trim())} /> : undefined}
              columnsEditor={
                !isBoard && view
                  ? {
                      catalog: fullColumnCatalog,
                      ids: listColumnIds,
                      canEdit: Boolean(view.can_edit),
                      onChange: (ids) => updateColumns.mutate(ids),
                      onResetWidths: colWidths.resetWidths,
                    }
                  : undefined
              }
              cardDesigner={
                isBoard && view
                  ? {
                      onOpen: () => setDesigningCard(true),
                      canEdit: Boolean(view.can_edit),
                    }
                  : undefined
              }
            />
          )}
          {updateColumns.isError && (
            <span className="text-xs text-red-400">
              Columns: {errorMessage(updateColumns.error)}
            </span>
          )}
          {updateCardLayout.isError && (
            <span className="text-xs text-red-400">
              Card layout: {errorMessage(updateCardLayout.error)}
            </span>
          )}
          {move.isError && (
            <span className="text-xs text-red-400">Move failed: {errorMessage(move.error)}</span>
          )}
          {updateWipLimits.isError && (
            <span className="text-xs text-red-400">
              WIP limit: {errorMessage(updateWipLimits.error)}
            </span>
          )}
          {deleteView.isError && (
            <span className="text-xs text-red-400">{errorMessage(deleteView.error)}</span>
          )}
          {confirmingDelete && canManageView && (
            <Button
              variant="ghost"
              className="text-red-400 hover:text-red-300"
              onClick={() => deleteView.mutate(view)}
              disabled={deleteView.isPending}
            >
              {deleteView.isPending ? "Deleting…" : "Confirm delete?"}
            </Button>
          )}
          {/* Secondary view actions fold behind ⋯ — the reference bar keeps
              row 1 to identity + the few always-used knobs. */}
          <DropdownMenu
            label="View actions"
            align="end"
            items={[
              // The old second band's one-tab "Reports" nav, folded in here.
              // Open to a visitor too (RADD-1150): every report folds over the
              // same row filter as the lists, so the numbers match what they see.
              ...(project
                ? [
                    {
                      kind: "action" as const,
                      label: "Project reports",
                      icon: BarChart3,
                      onSelect: () =>
                        void navigate({
                          to: RoutePath.projectReports,
                          params: { projectKey: project.key },
                        }),
                    },
                    { kind: "separator" as const },
                  ]
                : []),
              {
                kind: "action",
                label: "Export CSV",
                icon: Download,
                disabled: pageItems.length === 0,
                onSelect: () => downloadCsv(view.name, itemsToCsv(pageItems)),
              },
              ...(canEditView
                ? [
                    {
                      kind: "action" as const,
                      label: "Edit view",
                      icon: Pencil,
                      onSelect: () => setEditing(true),
                    },
                  ]
                : []),
              ...(canManageView
                ? [
                    { kind: "separator" as const },
                    {
                      kind: "action" as const,
                      label: "Delete view…",
                      icon: Trash2,
                      danger: true,
                      onSelect: () => setConfirmingDelete(true),
                    },
                  ]
                : []),
            ]}
          />
        </div>
      </header>


      {isPlanning && cycles.isPending && <p role="status" className="px-4 py-2 text-xs text-fg-muted">Loading sprint sections…</p>}
      {isPlanning && cycles.isError && <p role="alert" className="px-4 py-2 text-xs text-fg-muted">Could not load sprint sections. <button className="underline" onClick={()=>void cycles.refetch()}>Retry sprints</button></p>}
      {isPlanning && (itemsTotal.isError || openSprintCount.isError || recoveryItems.countError) && <p role="status" className="px-4 py-2 text-xs text-fg-muted">Some Planning counts are unavailable. Displayed rows may still be used.</p>}
      {isPlanning && updateBucketOrder.isError && <p role="alert" className="px-4 py-2 text-sm text-fg-muted">Could not save sprint visibility. {errorMessage(updateBucketOrder.error)}</p>}
      {items.isPending ? (
        <Spinner label="Loading items…" />
      ) : items.isError ? (
        <div className="p-10">
          <QueryError label="items" error={items.error} />
        </div>
      ) : isMissingType && view ? (
        // The view's plugin type is gone (plugin disabled/uninstalled) — explain, don't silently
        // fall back to a builtin surface.
        <MissingPluginType typeKey={view.view_type} kind="view" />
      ) : isDisabledPluginView && view ? (
        // The type exists but is turned off — same clear notice, not a blank surface.
        <MissingPluginType typeKey={view.view_type} kind="view" disabled />
      ) : isPluginView && view ? (
        // A plugin-contributed view type (spec 94): its own `view.type` surface, handed the view +
        // its loaded (permission-scoped) items.
        <Slot id={SlotId.viewType} match={view.view_type} view={view} items={pageItems} />
      ) : isRoadmap ? (
        // Roadmap views (spec 79): the spec-77/78 timeline as a view surface.
        // Remount per view so zoom/extension/collapse/tray state re-initialize;
        // items arrive fetched (fetch-all) + quick-filtered + SLQ-bar-filtered.
        <RoadmapSurface
          key={view.id}
          // The NARROWED view (perf wave): its query_string keys the item
          // cache the editing gestures paint, so it must match the fetch.
          view={fetchQueryView ?? view}
          project={project}
          items={pageItems}
          canUpdate={canUpdate}
          rankOrdered={rankOrdered}
          filtered={slqFilter.active}
          trayQuery={roadmapTrayQuery}
          trayProjectId={view.project_id ?? null}
          showClosed={showClosed}
          onToggleShowClosed={toggleShowClosed}
          epicsOnly={epicsOnly}
          onToggleEpicsOnly={toggleEpicsOnly}
          membersCount={memberItems.length}
          membersOnly={memberFiltering}
          onToggleMembersOnly={toggleMembersOnly}
          memberIds={memberIds}
          onToggleMember={toggleMember}
          onToggleMembers={(ids, make) => void toggleMembers(ids, make)}
          canCurate={Boolean(view.can_edit)}
          truncated={roadmapTruncated}
          onLoadMore={() => setRoadmapAutoCap((cap) => cap + ROADMAP_MAX_AUTO_PAGES)}
        />
      ) : pageItems.length === 0 && !cycleGrouped ? (
        <p className="p-10 text-center text-sm text-fg-faint">
          {slqFilter.active ? "No items match this query." : "No items match this view."}
        </p>
      ) : (
        // The scale slider zooms the whole item surface (rows/cards, not chrome).
        <div
          className="flex min-h-0 flex-1 flex-col"
          style={{ zoom: display.scale }}
        >
          {view.view_type === ViewType.board ? (
            laneAxis ? (
              <ViewSwimlanes
                // Remount per view so the collapse set re-reads its storage key.
                key={view.id}
                columns={visibleColumns}
                collapseEmpty={collapseEmpty}
                lanes={lanes}
                viewId={view.id}
                layout={cardLayout}
                usersById={usersById}
                cfByKey={cfByKey}
                slaByItem={slaByItem}
                rollupByItem={rollupByItem}
                timelogByItem={timelogByItem}
                onMoveToCell={columnDraggable || laneDraggable ? moveToCell : undefined}
                onContextMenu={openContextMenu}
                selectedIds={selectable ? selected : undefined}
                onSelectToggle={selectable ? onSelectToggle : undefined}
              />
            ) : (
              <ViewBoard
                groups={visibleColumns}
                collapseEmpty={collapseEmpty}
                layout={cardLayout}
                usersById={usersById}
                cfByKey={cfByKey}
                slaByItem={slaByItem}
                rollupByItem={rollupByItem}
                timelogByItem={timelogByItem}
                onQuickAdd={
                  canCreate && columnAxis
                    ? (bucket) => openCreate(bucketCreatePreset(columnAxis, bucket))
                    : undefined
                }
                showPoints={pointsEnabled && stateColumns}
                onLoadColumn={isGrouped ? groupedItems.loadColumn : undefined}
                columnLoading={groupedItems.columnLoading}
                columnError={groupedItems.columnError}
                columnHasMore={groupedItems.columnHasMore}
                wipLimits={stateColumns ? view.wip_limits ?? undefined : undefined}
                onSetWipLimit={canSetWipLimit ? setWipLimit : undefined}
                onMoveToBucket={columnDraggable ? moveToBucket : undefined}
                onContextMenu={openContextMenu}
                selectedIds={selectable ? selected : undefined}
                onSelectToggle={selectable ? onSelectToggle : undefined}
              />
            )
          ) : (
            <ViewList
              groups={isPlanning ? sectionSearch.apply(visibleColumns) : isGrouped ? visibleColumns : columns}
              sectionSearch={isPlanning ? sectionSearch.control : undefined}
              sectionStatus={isPlanning ? group => {
                const query = group.key === BACKLOG_KEY ? pagedItems : group.key === RESCHEDULING_KEY ? recoveryItems : group.key.startsWith("history:") ? historyItems : sprintItems;
                return query.isPending ? <p role="status" className="px-4 py-2 text-xs text-fg-muted">Loading {group.label}…</p>
                  : query.isError ? <p role="alert" className="px-4 py-2 text-xs text-fg-muted">Could not refresh {group.label}. <button className="underline" onClick={()=>void query.refetch()}>Retry section</button></p> : null;
              } : undefined}
              sectionTools={isPlanning ? group => group.key === BACKLOG_KEY ? <Select aria-label="Backlog order" size="sm" value={planningOptions.backlogOrder} onChange={value => changePlanning({backlogOrder: value as PlanningOptions["backlogOrder"]})} options={[{value:"priority",label:"Priority"},{value:"recent",label:"Recently updated"},{value:"manual",label:"Manual"}]} /> : null : undefined}
              viewId={view.id}
              display={display}
              slaByItem={slaByItem}
              rollupByItem={rollupByItem}
              listColumns={listColumns}
              columnWidths={colWidths.widths}
              onColumnsApply={colWidths.applyWidths}
              onColumnsCommit={colWidths.commitWidths}
              timelogByItem={timelogByItem}
              usersById={usersById}
              cycleStatsProjectId={view.project_id ?? undefined}
              onMoveToBucket={columnDraggable ? moveToBucket : undefined}
              onContextMenu={openContextMenu}
              selectedIds={selectable ? selected : undefined}
              onSelectToggle={selectable ? onSelectToggle : undefined}
              onStar={onStar}
              // Queues order by SLA urgency — manual drag-rank would fight it.
              onReorder={(isPlanning || rankOrdered) && canUpdate && !isQueue ? onReorder : undefined}
            />
          )}
        </div>
      )}

      {isGrouped && <div className="flex flex-wrap items-center justify-center gap-3 border-t border-subtle p-3 text-sm">
        {(groupedItems.first?.total_groups ?? 0) > 20 && <>
          <span>Group set {groupedItems.group + 1} of {Math.ceil((groupedItems.first?.total_groups ?? 0)/20)}</span>
          <Button variant="secondary" size="sm" disabled={!groupedItems.group || groupedItems.isFetching} onClick={()=>groupedItems.setGroup(groupedItems.group-1)}>Previous groups</Button>
          <Button variant="secondary" size="sm" disabled={(groupedItems.group+1)*20 >= (groupedItems.first?.total_groups ?? 0) || groupedItems.isFetching} onClick={()=>groupedItems.setGroup(groupedItems.group+1)}>Next groups</Button>
        </>}
        {groupedItems.hasNextPage ? <>
          <span>{view.view_type === "board" && !laneAxis ? "Load more using the button in each column." : "Loaded rows are a slice of each group."}</span>
          {!(view.view_type === "board" && !laneAxis) && <Button variant="secondary" size="sm" disabled={groupedItems.isFetching} onClick={()=>void groupedItems.fetchNextPage()}>{groupedItems.isFetching ? "Loading…" : "Load more in these groups"}</Button>}
        </> : <span className="text-fg-muted">All issues in this group set are loaded.</span>}
        {groupedItems.isFetchNextPageError && <span role="alert">Could not load more. Try again.</span>}
      </div>}
      {isPlanning && (recoveryItems.more || (planningOptions.history && historyItems.more)) && <div className="flex flex-wrap items-center gap-3 border-t border-subtle p-3 text-xs text-fg-muted">
        {recoveryItems.more && <Button variant="secondary" size="sm" disabled={recoveryItems.isFetchingNextPage} onClick={recoveryItems.loadMore}>Load more issues needing rescheduling</Button>}
        {planningOptions.history && historyItems.more && <Button variant="secondary" size="sm" disabled={historyItems.isFetchingNextPage} onClick={historyItems.loadMore}>Load more history</Button>}
        {(recoveryItems.isFetchNextPageError || historyItems.isFetchNextPageError) && <span role="alert">Could not load more issues. Try again.</span>}
      </div>}
      {isPlanning && planningOptions.history && historyItems.isError && <p role="alert" className="p-3 text-sm text-fg-muted">Could not load sprint history. <Button variant="secondary" size="sm" onClick={() => void historyItems.refetch()}>Retry history</Button></p>}
      {isPlanning && sprintItems.more && (
        <div role="status" className="border-t border-subtle px-4 py-2 text-sm text-fg-muted">
          {sprintItems.isFetchingNextPage ? "Loading more sprint work…" : "More sprint work is available."}
          {(sprintItems.paused || sprintItems.isFetchNextPageError) && <button type="button" className="ml-3 underline" onClick={sprintItems.loadMore}>Load more sprint work</button>}
          <span className="ml-2">Issue rows are still loading; sprint statistics cover the whole sprint.</span>
        </div>
      )}
      {/* Classic pagination (pagination wave) — roadmaps auto-stream instead. */}
      {/* RADD-1177: also shown whenever a SMALLER page would paginate — otherwise
          the size picker is unreachable exactly when someone wants a smaller page. */}
      {!isRoadmap && !isGrouped && !(isPlanning && sectionSearch.backlogFiltered) &&
        ((pageCount !== null && pageCount > 1) ||
          page > 1 ||
          (totalCount !== null && totalCount > Math.min(...ITEMS_PAGE_SIZES))) && (
        <div className="flex items-center justify-center border-t border-subtle/70 py-2">
          {isPlanning && <span className="mr-3 text-xs text-fg-muted">Open backlog</span>}
          <Pager
            page={page}
            pageCount={pageCount}
            total={totalCount}
            onPage={setPage}
            pageSize={pageLimit}
            pageSizes={ITEMS_PAGE_SIZES}
            onPageSize={(size) => {
              // A new page size makes the page NUMBER meaningless — back to 1.
              setPageLimit(size);
              setPage(1);
            }}
          />
        </div>
      )}

      {selectable && selected.size > 0 && (
        <BulkActionBar
          selectedIds={selected}
          project={project}
          matching={matching}
          onClear={() => {
            setSelected(new Set());
            setAnchor(null);
          }}
        />
      )}

      {menu && (
        <ItemContextMenu
          item={menu.item}
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          canUpdate={canUpdate}
          onChooseCycle={() => setCycleTarget(menu.item)}
          states={states.data}
          currentUser={currentUser}
          onAct={(patch, optimistic) =>
            move.mutate({ itemId: menu.item.id, patch, optimistic })
          }
          onStar={onStar}
        />
      )}

      {cycleTarget && <CycleChoices value={cycleTarget.cycle?.id ?? ""} includeCompleted={false}
        emptyLabel="Backlog" onClose={() => setCycleTarget(null)} onSelect={cycle => {
          move.mutate({ itemId: cycleTarget.id, patch: { cycle_id: cycle?.id ?? null },
            optimistic: { cycle: cycle ? { id: cycle.id, name: cycle.name, status: cycle.status } : null } });
          setCycleTarget(null);
        }} />}

      {editing && (
        <ViewModal project={project} view={view} onClose={() => setEditing(false)} />
      )}

      {designingCard && view && (
        <CardDesignerModal
          view={view}
          fields={fields.data ?? []}
          canEdit={Boolean(view.can_edit)}
          onSave={(layout) => updateCardLayout.mutate(layout)}
          onClose={() => setDesigningCard(false)}
        />
      )}

      {creating && project && (
        <NewItemModal
          project={project}
          initial={createInitial}
          onClose={() => setCreating(false)}
        />
      )}
    </div>
  );
}

/** Inline "Save filter" affordance: names the CURRENT ad-hoc SLQ query and
 * stores it as a personal chip (lib/topbar-prefs). Chip-sized closed; a tiny
 * name form open — Enter saves, Escape backs out. */
function SaveFilterButton({ onSave }: { onSave: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    onSave(trimmed);
    setName("");
    setOpen(false);
  };
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Save the current filter as a personal chip"
        className="flex items-center gap-1 rounded-full border border-dashed border-strong px-2.5 py-0.5 text-xs text-fg-muted transition-colors hover:border-emphasis hover:text-fg cursor-pointer"
      >
        <BookmarkPlus size={12} aria-hidden />
        Save filter
      </button>
    );
  }
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex items-center gap-1"
    >
      <input
        value={name}
        onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        placeholder="Filter name…"
        autoFocus
        maxLength={60}
        className="h-6 w-36 rounded-full border border-strong bg-surface px-2.5 text-xs text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      <Button type="submit" size="sm" disabled={name.trim() === ""}>
        Save
      </Button>
    </form>
  );
}
