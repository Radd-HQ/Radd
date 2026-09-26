import { useBoardItems, boardGroups } from "../lib/useBoardItems";
import { Select } from "../components/Select";
import { BACKLOG_KEY } from "../lib/view-utils";
import { usePlanningSectionSearch } from "../lib/usePlanningSectionSearch";
import { PlanningControls } from "../components/views/PlanningControls";
import { accountStorageKey } from "../lib/account-storage";
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
import { useNavigate, useParams, Link } from "@tanstack/react-router";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, BookmarkPlus, Download, Globe, Pencil, Pin, Plus, Rocket, RotateCcw, SearchCode, Trash2, UserRound, X } from "lucide-react";
import { Slot, SlotId, useDisabledMatches, Pager, useDebounced, useItemAttributes } from "@radd/plugin-sdk";
import { ItemAttributeContext, useItemAttributeValues } from "../lib/item-attribute-data";
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
import { useCurrentUser, useKeyboardShortcut, usePermissions, usePointsEnabled, useAnonymousBounce, useIsAuthenticated, useItemsPageLimit } from "../lib/hooks";
import { cyclesQuery, infiniteViewItemsQuery, itemIdsQuery, itemsCountQuery, pagedViewItemsQuery, queryKeys, roadmapMembersQuery, statesQuery, useTimelogBatches, usersQuery, viewQuery as viewDefinitionQuery, allStatesQuery, stateCategoriesQuery } from "../lib/queries";
import { pushToast } from "../lib/toast";
import { useReorderItem, useToggleStar, useUpdateItemInView } from "../lib/item-mutations";
import {
  bucketCreatePreset,
  bucketMovePlan,
  dragEnabledForAxis,
  type BucketCreatePreset,
  type BucketRef,
} from "../lib/axis-dnd";
import { ItemKind, Permission, ViewAxis, ViewType, type Item, type View } from "../lib/types";
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
  useCardDisplay,
} from "../lib/card-display";
import { isBuiltinViewType, useViewTypes, viewTypeHasAxes, viewTypeIcon } from "../lib/view-types";
import {
  activeCardLayout,
  placedAttrSet,
  placedCustomFieldKeys,
} from "../lib/card-layout";
import { CardDesignerModal } from "../components/views/carddesigner/CardDesignerModal";
import { Button } from "../components/Button";
import { DropdownMenu } from "../components/DropdownMenu";
import { Spinner } from "../components/Spinner";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { ItemContextMenu } from "../components/items/ItemContextMenu";
import { NewItemModal } from "../components/items/NewItemModal";
import { useRollupBatch } from "../components/items/RollupBar";
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
  useUrlChipSet,
  writeUrlState,
} from "../lib/url-state";
import { ViewBoard } from "../components/views/ViewBoard";
import { FLAT_GROUP_KEY, ViewList } from "../components/views/ViewList";
import { ViewModal } from "../components/views/ViewModal";
import { ViewSwimlanes } from "../components/views/ViewSwimlanes";
import { RoadmapSurface } from "../components/roadmap/RoadmapSurface";
import { QueryError } from "../components/QueryError";
import { CycleModal } from "./settings/cycles";
import { fieldsQuery } from "@radd-plugin-ui/fields/catalog";
import { projectByIdQuery } from "@radd-plugin-ui/projects/directory-queries";
import { FieldType } from "@radd-plugin-ui/fields/types";

/** A localStorage-backed on/off flag ("1"/"0"), re-read when the key changes. */
function useStoredFlag(storageKey: string): [boolean, () => void] {
  const [on, setOn] = useState(() => window.localStorage.getItem(storageKey) === "1");
  useEffect(() => {
    setOn(window.localStorage.getItem(storageKey) === "1");
  }, [storageKey]);
  const toggle = () => {
    setOn((current) => {
      window.localStorage.setItem(storageKey, current ? "0" : "1");
      return !current;
    });
  };
  return [on, toggle];
}

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
  const [newCycle, setNewCycle] = useState(false);
  const currentUser = useCurrentUser();

  const views = useQuery(viewDefinitionQuery(viewId));
  // Spec 121: a visitor who cannot see this view signs in instead (hook order:
  // this runs on every render, ahead of the early returns below).
  useAnonymousBounce(views.isError);
  const authenticated = useIsAuthenticated();
  const view = views.data;
  // A plugin-contributed view type (spec 94): rendered by the plugin's `view.type` slot instead of
  // the builtin board/list surface — or, when it declares a LIST surface (RADD-1396), by the host's
  // list over the plugin's own rows. The header/query bar apply either way.
  const viewTypes = useViewTypes();
  const typeOption = view ? viewTypes.byKey.get(view.view_type) : undefined;
  const listSurface = typeOption?.list_surface ?? null;
  const isPluginView = Boolean(typeOption) && !listSurface;
  const isBuiltinView = view != null && isBuiltinViewType(view.view_type);
  // Neither builtin nor a currently-available plugin type → its plugin was disabled/uninstalled.
  const isMissingType = view != null && !isBuiltinView && !typeOption && viewTypes.loaded;
  // A plugin type's surface (its rows endpoint, its slot) is unknown until capabilities answer.
  const typeResolved = isBuiltinView || viewTypes.loaded;
  // The plugin is enabled but this view TYPE has been turned off (per-user/instance-wide) — its
  // `view.type` surface won't render, so show the "turned off" notice rather than a blank page.
  const disabledViewTypes = useDisabledMatches(SlotId.viewType);
  const isDisabledPluginView =
    view != null && isPluginView && disabledViewTypes.has(view.view_type);
  const projectLookup = useQuery(projectByIdQuery(view?.project_id ?? ""));
  const project = projectLookup.data ?? null;

  // Quick filters (the view's shared chips, URL `f`) and the user's PERSONAL saved-filter chips
  // (URL `pf`): active ones AND into the query, and the whole machinery (fetch, optimistic
  // drag/star/reorder caches) targets the FILTERED dataset via this effective view.
  const quickChips = useUrlChipSet("f", viewId);
  const activeFilters = quickChips.active;
  const toggleFilter = quickChips.toggle;
  const savedFilters = useSavedFilters();
  const navPins = useNavPins();
  const personalChips = useUrlChipSet("pf", viewId);
  const activePersonal = personalChips.active;
  const togglePersonal = personalChips.toggle;
  const resetView = () => {
    clearUrlState();
    if (viewId) clearViewDisplayState(viewId);
    quickChips.clear();
    personalChips.clear();
    slqFilter.runQuery("");
    // Display prefs are read at mount, so a reload is the honest way to show
    // the restored defaults rather than half-applying them.
    window.location.reload();
  };
  // The COMMITTED bar query composes into the fetch like a quick filter: conditions AND in, its
  // ORDER BY replaces the view's.
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

  // A roadmap fetches only epics and dated bars (the constants explain why);
  // "Show closed" off hides every closed item.
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

  const [showClosed, toggleShowClosed] = useStoredFlag(roadmapShowClosedStorageKey(viewId));
  // "Epics only" (default off) swaps in the tighter epics-and-their-children clause.
  const [epicsOnly, toggleEpicsOnly] = useStoredFlag(roadmapEpicsOnlyStorageKey(viewId));
  // Curated membership: read through the item dialect's `roadmap` field (hydrated + RBAC-scoped).
  // With members and no stored override the roadmap opens members-only, so pinning the first item
  // is what makes a roadmap curated.
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

  // Axes are a board's and a list's; planning is always cycle-grouped, and every other type
  // (roadmap, a plugin's) ignores whatever axes it stored.
  const axesApply = viewTypeHasAxes(view?.view_type);
  const columnAxis =
    view?.view_type === ViewType.planning
      ? ViewAxis.cycle
      : axesApply
        ? (view?.group_by ?? (view?.view_type === ViewType.board ? ViewAxis.state : null))
        : null;
  const laneAxis = view?.view_type === ViewType.board ? view.swimlane_by : null;
  const isGrouped = Boolean(view && axesApply && columnAxis);
  // RADD-1291: a project view plans with ITS cycles (homed there or holding its issues).
  const cycles = useQuery({ ...cyclesQuery(undefined, view?.project_id ?? undefined), enabled: Boolean(view) && (
    view?.view_type === ViewType.planning || view?.group_by === ViewAxis.cycle || view?.swimlane_by === ViewAxis.cycle
  ) });
  const planning = useMemo(() => planningQueries(fetchQueryView, cycles.data, {...planningOptions, search: backlogSearch}), [fetchQueryView, cycles.data, planningOptions, backlogSearch]);
  const isBoard = view?.view_type === ViewType.board;
  const boardItems = useBoardItems(fetchQueryView, columnAxis, isBoard ? laneAxis : null, cycles.data, isGrouped && (!(columnAxis === "cycle" || (isBoard && laneAxis === "cycle")) || cycles.isSuccess));
  const pagedFetchView = isPlanning ? planning.backlog : fetchQueryView;
  const sprintItems = usePlanningSprints(planning.sprints, isPlanning && cycles.isSuccess && planning.cycleCount > 0);
  const recoveryItems = usePlanningSprints(planning.recovery, isPlanning && cycles.isSuccess, 1);
  const historyItems = usePlanningSprints(planning.history, isPlanning && planningOptions.history && Boolean(planning.historyId), 1);
  const sectionSearch = usePlanningSectionSearch(planning, isPlanning && cycles.isSuccess, accountStorageKey(`planning-search:${viewId}`), planningOptions.history);
  const openSprintCount = useQuery({
    ...planningCountQuery(planning.sprintOpen),
    enabled: isPlanning && cycles.isSuccess && planning.cycleCount > 0,
  });

  // Roadmaps auto-stream their (narrowed) match set below; every other view type pages its result
  // behind a Pager, the page carried in the URL (Planning pages only its backlog).
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
    ...pagedViewItemsQuery(pagedFetchView, page, pageLimit, listSurface),
    enabled: Boolean(view) && typeResolved && !isMissingType && !isRoadmap && !isGrouped,
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
    data: isBoard || isGrouped ? boardItems.items : isRoadmap ? roadmapFlat : isPlanning ? sectionSearch.displayItems([
      ...planning.scheduled.filter(g => !view?.hidden_columns?.includes(g.key)).map(g => ({key: g.key, items: sprintItems.items.filter(i => i.cycle?.id === g.key)})),
      {key: RESCHEDULING_KEY, items: recoveryItems.items},
      {key: BACKLOG_KEY, items: pagedItems.data ?? []},
      ...(planningOptions.history && planning.historyId ? [{key: `history:${planning.historyId}`, items: historyItems.items}] : []),
    ]) : pagedItems.data,
    isPending: isPlanning ? false : isBoard || isGrouped ? boardItems.isPending && !cycles.isError : isRoadmap ? itemPages.isPending : pagedItems.isPending,
    isError: isPlanning ? false : isBoard ? (boardItems.isError && !boardItems.data) || ((columnAxis === "cycle" || laneAxis === "cycle") && cycles.isError) : isGrouped ? (boardItems.isError && !boardItems.data) || (columnAxis === "cycle" && cycles.isError) : isRoadmap ? itemPages.isError : pagedItems.isError,
    error: isBoard || isGrouped ? boardItems.error ?? cycles.error : isRoadmap ? itemPages.error : pagedItems.error ?? (isPlanning ? cycles.error ?? recoveryItems.error ?? sprintItems.error : null),
  };
  const pageItems = useMemo(() => [...new Map((items.data ?? []).map(item => [item.id, item])).values()], [items.data]);

  // Per-view card display (slots/labels/scale) — persisted under the view's id.
  const cardDisplay = useCardDisplay(
    `view:${viewId}`,
    isBoard ? DEFAULT_BOARD_SLOTS : DEFAULT_LIST_SLOTS,
  );
  const display = cardDisplay.display;
  // Table columns (spec 108), list-type surfaces only (boards keep chip slots):
  // the SET comes from the saved view (shared), widths from localStorage
  // (personal). `fields` also feeds the axis pickers further down.
  const fields = useQuery(fieldsQuery());
  const listColumnIds = useMemo(
    () => view?.columns ?? [...defaultColumnsFor(view?.view_type, listSurface?.columns)],
    [view?.columns, view?.view_type, listSurface?.columns],
  );
  // Plugin-contributed columns/cells (RADD-1394), withdrawn live with their plugin.
  const attributes = useItemAttributes();
  const fullColumnCatalog = useMemo(
    () => columnCatalog(fields.data ?? [], view?.project_id ?? null, attributes),
    [fields.data, view?.project_id, attributes],
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
  // Contributed attributes: each one shown as a list column or a placed card
  // cell asks its owner's source once per page of rows; the rest ask nothing.
  const pageItemIds = useMemo(() => pageItems.map((item) => item.id), [pageItems]);
  const attributeData = useItemAttributeValues(
    attributes,
    isRoadmap ? [] : attributes.filter((attribute) => hasCardAttr(attribute.id) || hasListColumn(attribute.id)),
    pageItemIds,
  );
  // Epic progress (spec 76): one rollup batch for the page's EPIC-kind items —
  // fetched only while the progress slot/column is on and epics are visible.
  const epicIds = useMemo(
    () => pageItems.filter((item) => item.kind === ItemKind.epic).map((item) => item.id),
    [pageItems],
  );
  // Roadmaps draw bars, not cards — no attribute/rollup batches over the full fetch.
  const rollupByItem = useRollupBatch(
    epicIds,
    !isRoadmap && (hasCardAttr("progress") || hasListColumn("progress")),
  );
  // Logged time on cards: one chunked batch over the page's items while the
  // slot/column is on. Quiet-degrade (retry: false in the query) — cards just
  // omit the readout when timelogging is off or the batch fails.
  const timelogByItem = useTimelogBatches(pageItemIds,
    authenticated && !isRoadmap && (hasCardAttr("logged_time") || hasListColumn("logged_time")));

  // The server's order stands: the view's SLQ ORDER BY, or a plugin list type's own rows endpoint.
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
  // Story points, resolved per project (the instance default on all-projects views): Σ pts headers.
  const pointsEnabled = usePointsEnabled(view?.project_id ?? undefined);

  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  // New-item affordance on project-scoped views. `c` = create.
  const canCreate = Boolean(project) && perms.project(project, Permission.itemCreate);
  // Board quick-add (spec-24 axis semantics, reversed): the + / "Add issue"
  // affordances seed the modal with the column's bucket value. Cleared on
  // every other entry path so a plain "New issue" never inherits a column.
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
  // A PLANNING view is always cycle-grouped; other non-board/list types are flat
  // (both ignore their stored axes — `axesApply` above).
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
    if (!columnAxis) return [{ key: FLAT_GROUP_KEY, label: "All issues", items: orderedItems }];
    if (isPlanning) return planningGroups(planning, sprintItems.items, recoveryItems.items,
      pagedItems.data ?? [], historyItems.items, cycles.data, planningOptions,
      Boolean(fetchQueryView?.query.trim()), recoveryItems.total, totalCount ?? undefined,
      historyItems.total, Boolean(sprintItems.more)).map(group => {
        const query = group.key === BACKLOG_KEY ? pagedItems : group.key === RESCHEDULING_KEY ? recoveryItems : group.key.startsWith("history:") ? historyItems : sprintItems;
        return {...group, emptyMessage: query.isPending || query.isError ? undefined : group.emptyMessage};
      });

    // RADD-855: the view's own bucket order, over the axis's natural order.
    return applyBucketOrder(
      (isGrouped ? boardGroups(groupItemsForView(orderedItems, columnAxis, axisContext), columnAxis, boardItems.first, false, allStates.data, groupItemsForView([], columnAxis, axisContext).map(g=>g.key)) : groupItemsForView(orderedItems, columnAxis, axisContext).map(g => ({...g,total:isGrouped ? boardItems.first?.column_totals[g.key] ?? 0 : undefined, totalPoints:isGrouped ? boardItems.first?.column_points?.[g.key] : undefined}))),
      view.column_order,
    );
  }, [isBoard, boardItems.first, view, orderedItems, columnAxis, axisContext, isGrouped, isPlanning, planning, sprintItems.items, recoveryItems.items, pagedItems.data, historyItems.items, cycles.data, planningOptions, fetchQueryView, recoveryItems.total, totalCount, historyItems.total, sprintItems.more, pagedItems.isPending, pagedItems.isError, recoveryItems.isPending, recoveryItems.isError, historyItems.isPending, historyItems.isError, sprintItems.isPending, sprintItems.isError]);
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
            (isBoard ? boardGroups(groupItemsForView(orderedItems, laneAxis, axisContext), laneAxis, boardItems.first, true, allStates.data, groupItemsForView([], laneAxis, axisContext).map(g=>g.key)) : groupItemsForView(orderedItems, laneAxis, axisContext).map(g => ({...g,total:isGrouped ? boardItems.first?.lane_totals[g.key] ?? 0 : undefined}))),
            view.swimlane_order,
          )
        : [],
    [isBoard, boardItems.first, view, orderedItems, laneAxis, axisContext, isGrouped],
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
  // All-projects views have no single project: ask "held anywhere" (RADD-788); the server
  // re-checks each reorder.
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
      // Name-keyed drop that couldn't resolve: the issue's project has no state
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

  // "Select all N matching": GET /items/ids over the same composed query the page shows, fetched
  // lazily once a selection exists.
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
  const TypeIcon = viewTypeIcon(view.view_type, typeOption);
  // Multi-select + bulk (spec 68): every surface incl. boards, gated on
  // item.update in scope.
  const selectable = canUpdate;

  const axisSummary = [
    // Only a board's and a list's axes apply — don't announce the ones another type ignores.
    view.group_by && axesApply
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

      {/* ONE header row: identity, the SAVED chips, then count/knobs at the right edge. */}
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

        {/* SAVED chips — the view's shared quick filters plus the user's personal saved filters. */}
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
              quickChips.clear();
              personalChips.clear();
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
              ? // RADD-1293: the total, not paging internals ("100 loaded · … matching items").
                `${Object.values(boardItems.first?.column_totals ?? {}).reduce((a,b)=>a+b,0).toLocaleString()} issues`
              : isPlanning
              ? `${planning.cycleCount ? openSprintCount.data?.total.toLocaleString() ?? "…" : "0"} open sprint issues · ${totalCount?.toLocaleString() ?? "…"} backlog · ${recoveryItems.total?.toLocaleString() ?? "…"} need rescheduling`
              : isRoadmap
              ? // RADD-1293: the roadmap's own toolbar counts what is scheduled;
                // a second count here said the same thing in other words.
                ""
              : totalCount !== null
                ? `${totalCount.toLocaleString()} items`
                : `${pageItems.length} items`}
          </span>
          {axisSummary && <span className="text-xs text-fg-muted">{axisSummary}</span>}
          {/* Plugin-contributed view header items (spec 94): a plugin attached to a view gets the
              view + its loaded, permission-scoped items — it can compute over exactly what the user
              can see. */}
          <Slot id={SlotId.viewHeader} view={view} items={items.data ?? []} />
          {/* RADD-1291: a project's managers plan its sprints from here, homed in it. */}
          {isPlanning && project && (perms.global(Permission.cycleCreate) || perms.project(project, Permission.projectManage)) && (
            <Button size="sm" variant="secondary" onClick={() => setNewCycle(true)} data-new-cycle>
              <Plus size={13} aria-hidden />
              New cycle
            </Button>
          )}
          {newCycle && project && (
            <CycleModal cycle={null} defaultProjectId={project.id} onClose={() => setNewCycle(false)} />
          )}
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
          {axesApply && Boolean(view?.can_edit) && columnAxis && (
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
          {/* Roadmaps carry their own knobs (spec 79) — no display config. */}
          {!isRoadmap && (
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
          {/* The project's other pages, one click from any of its views (RADD-1290). */}
          {project && (
            <nav aria-label="Project pages" className="flex items-center gap-0.5">
              <Link to={RoutePath.projectReports} params={{ projectKey: project.key }} data-view-link="reports"
                className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-fg-secondary hover:bg-overlay hover:text-heading focus-visible:outline-2 focus-visible:outline-focus">
                <BarChart3 size={13} aria-hidden />
                Reports
              </Link>
              <Link to={RoutePath.projectReleases} params={{ projectKey: project.key }} data-view-link="releases"
                className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-fg-secondary hover:bg-overlay hover:text-heading focus-visible:outline-2 focus-visible:outline-focus">
                <Rocket size={13} aria-hidden />
                Releases
              </Link>
            </nav>
          )}
          {/* Secondary view actions fold behind ⋯ — the reference bar keeps
              row 1 to identity + the few always-used knobs. */}
          <DropdownMenu
            label="View actions"
            align="end"
            items={[
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
      {isMissingType && view ? (
        // The view's plugin type is gone (plugin disabled/uninstalled) — explain, don't silently
        // fall back to a builtin surface. Checked before loading: nothing fetches its rows.
        <MissingPluginType typeKey={view.view_type} kind="view" />
      ) : isDisabledPluginView && view ? (
        // The type exists but is turned off — same clear notice, not a blank surface.
        <MissingPluginType typeKey={view.view_type} kind="view" disabled />
      ) : items.isPending ? (
        <Spinner label="Loading issues…" />
      ) : items.isError ? (
        <div className="p-10">
          <QueryError label="items" error={items.error} />
        </div>
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
          // The NARROWED view: its query_string keys the item cache the
          // editing gestures paint, so it must match the fetch.
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
      ) : pageItems.length === 0 && !cycleGrouped && !isGrouped && !isBoard ? (
        <p className="p-10 text-center text-sm text-fg-faint">
          {slqFilter.active ? "No issues match this query." : "No issues match this view."}
        </p>
      ) : (
        // The scale slider zooms the whole item surface (rows/cards, not chrome).
        <div
          className="flex min-h-0 flex-1 flex-col"
          style={{ zoom: display.scale }}
        >
          <ItemAttributeContext.Provider value={attributeData}>
          {view.view_type === ViewType.board ? (
            laneAxis ? (
              <ViewSwimlanes
                // Remount per view so the collapse set re-reads its storage key.
                key={boardItems.scope}
                loading={boardItems}
                updating={boardItems.isFetching}
                columns={visibleColumns}
                collapseEmpty={collapseEmpty}
                lanes={lanes}
                viewId={view.id}
                layout={cardLayout}
                usersById={usersById}
                cfByKey={cfByKey}
                rollupByItem={rollupByItem}
                timelogByItem={timelogByItem}
                onMoveToCell={columnDraggable || laneDraggable ? moveToCell : undefined}
                onContextMenu={openContextMenu}
                selectedIds={selectable ? selected : undefined}
                onSelectToggle={selectable ? onSelectToggle : undefined}
              />
            ) : (
              <ViewBoard
                key={boardItems.scope}
                loading={boardItems}
                updating={boardItems.isFetching}
                groups={visibleColumns}
                collapseEmpty={collapseEmpty}
                layout={cardLayout}
                usersById={usersById}
                cfByKey={cfByKey}
                rollupByItem={rollupByItem}
                timelogByItem={timelogByItem}
                onQuickAdd={
                  canCreate && columnAxis
                    ? (bucket) => openCreate(bucketCreatePreset(columnAxis, bucket))
                    : undefined
                }
                showPoints={pointsEnabled && stateColumns}
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
              loading={isGrouped ? boardItems : undefined}
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
              // A plugin list type with its own rows owns their order — drag-rank would fight it.
              onReorder={(isPlanning || rankOrdered) && canUpdate && !listSurface?.rows_path ? onReorder : undefined}
            />
          )}
          </ItemAttributeContext.Provider>
        </div>
      )}

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
      {/* Classic pagination — roadmaps auto-stream instead. */}
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
            noun="issues"
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
