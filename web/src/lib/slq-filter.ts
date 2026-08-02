import { useCallback, useMemo, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ITEMS_PAGE_LIMIT } from "./constants";
import { SlqProbeStatus, useSlqValidation, type SlqProbe } from "./hooks";
import { infiniteSlqItemsQuery, slqItemsQuery } from "./queries";
import { slqErrorOf } from "./slq";
import { readUrlState, writeUrlState } from "./url-state";
import type { Item } from "./types";

/**
 * Page-level ad-hoc SLQ filtering (spec 55): the state behind the
 * `SlqFilterBar` every content page mounts under its filter controls.
 *
 * Two-phase by design — typing only VALIDATES (parse+compile server-side,
 * zero items I/O), Enter COMMITS and runs one real query. Speculative
 * intermediate drafts ("priority = high" on the way to "… AND label = x")
 * never hit the items table, which is what keeps this bar affordable on
 * projects with hundreds of thousands of issues.
 *
 * `filterItems` intersects the page's own content with the committed match
 * set, so the page keeps its layout, grouping, and order. The match set is
 * one page at the API cap — beyond it the status line reads "N+" (list-style
 * surfaces pass `paginate` and render `resultItems` with `loadMore` instead).
 */
export interface SlqPageFilter {
  draft: string;
  setDraft: (value: string) => void;
  /** Commit + execute the current draft (Enter). */
  run: () => void;
  /** Set AND run a query in one step (the NL→SLQ "Ask" flow). */
  runQuery: (q: string) => void;
  /** Editor status line: validation while typing, result count once run. */
  probe: SlqProbe;
  /** True once a committed query has produced a match set. */
  active: boolean;
  /** The committed query text ('' = none) — view pages COMPOSE it into their
   *  fetch (composeQueryWithBar) instead of intersecting (pagination wave). */
  committed: string;
  /** Intersect page content with the match set (pass-through while inactive). */
  filterItems: (items: Item[]) => Item[];
  /** paginate mode: the committed result set (server order), page-appended. */
  resultItems: Item[] | undefined;
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
}

export function useSlqPageFilter(
  scope: Record<string, string>,
  options?: { paginate?: boolean },
): SlqPageFilter {
  const paginate = options?.paginate ?? false;
  // Seed from the URL so a refresh (or a pasted link) lands on the same filtered
  // screen. Only the COMMITTED query is carried — an in-flight draft you never
  // pressed Enter on is not a state anyone wants restored.
  const initial = readUrlState().q ?? "";
  const [draft, setDraftState] = useState(initial);
  const [committed, setCommitted] = useState(initial);
  const validation = useSlqValidation(scope.project_id ?? null, draft);

  // The committed query fetches exactly once (then react-query caching rules);
  // never re-fired by typing. Single-page for intersection pages, offset-paged
  // where the result set is rendered directly. The unused twin stays disabled.
  const single = useQuery({
    ...slqItemsQuery(scope, committed),
    enabled: !paginate && committed !== "",
  });
  const paged = useInfiniteQuery({
    ...infiniteSlqItemsQuery(scope, committed),
    enabled: paginate && committed !== "",
  });
  const resultData = paginate ? paged.data?.pages.flat() : single.data;
  const resultFetching = paginate
    ? paged.isFetching && !paged.isFetchingNextPage
    : single.isFetching;
  const resultError = paginate
    ? paged.isError
      ? paged.error
      : null
    : single.isError
      ? single.error
      : null;

  const setDraft = useCallback((value: string) => {
    setDraftState(value);
    // Emptying the box clears the filter without needing a second Enter.
    if (value.trim() === "") {
      setCommitted("");
      writeUrlState({ q: null });
    }
  }, []);
  const commit = useCallback((value: string) => {
    const next = value.trim();
    setCommitted(next);
    writeUrlState({ q: next || null });
  }, []);
  const run = useCallback(() => commit(draft), [commit, draft]);
  const runQuery = useCallback(
    (q: string) => {
      setDraftState(q);
      commit(q);
    },
    [commit],
  );
  const { fetchNextPage } = paged;
  const loadMore = useCallback(() => {
    if (paginate) void fetchNextPage();
  }, [paginate, fetchNextPage]);

  const matchIds = useMemo(
    () => (committed !== "" && resultData ? new Set(resultData.map((item) => item.id)) : null),
    [committed, resultData],
  );
  const filterItems = useCallback(
    (items: Item[]) => (matchIds ? items.filter((item) => matchIds.has(item.id)) : items),
    [matchIds],
  );

  // Status line: validation feedback while composing; run state once the
  // settled draft IS the committed query. Editing after a run keeps the old
  // filter applied while the new draft shows "ready".
  let probe: SlqProbe;
  if (validation.status !== SlqProbeStatus.valid) {
    probe = validation; // idle | checking | invalid | failed
  } else if (validation.query !== committed) {
    probe = { ...validation, status: SlqProbeStatus.ready };
  } else if (resultError) {
    const slqError = slqErrorOf(resultError);
    probe = {
      status: slqError ? SlqProbeStatus.invalid : SlqProbeStatus.failed,
      query: committed,
      error: slqError,
      failure: !slqError && resultError instanceof Error ? resultError.message : null,
    };
  } else if (resultData === undefined || resultFetching) {
    probe = { ...validation, status: SlqProbeStatus.checking };
  } else {
    probe = {
      ...validation,
      count: resultData.length,
      atCap: paginate ? paged.hasNextPage ?? false : resultData.length >= ITEMS_PAGE_LIMIT,
    };
  }

  return {
    draft,
    setDraft,
    run,
    runQuery,
    probe,
    active: matchIds !== null,
    committed,
    filterItems,
    resultItems: paginate ? resultData : undefined,
    hasMore: paginate ? paged.hasNextPage ?? false : false,
    loadMore,
    isLoadingMore: paginate && paged.isFetchingNextPage,
  };
}

/** `useSlqQueryState` — the fetch-free sibling of `useSlqPageFilter` for
 * surfaces that filter SERVER-side by composing the committed query into
 * their OWN fetches (the timesheet's one query, every dashboard widget's
 * `q`, My Work's section queries). Same two-phase contract — typing only
 * validates, Enter commits, URL-synced under `q`, clearing the draft clears
 * the filter — but no match-set request and no client intersection. */
export interface SlqQueryState extends SlqPageFilter {
  /** The committed query text — AND it into the page's fetches
   *  (`combineQueryWithFilters(base, [committed])`). */
  committed: string;
}

export function useSlqQueryState(dialect?: string): SlqQueryState {
  const initial = readUrlState().q ?? "";
  const [draft, setDraft] = useState(initial);
  const [committed, setCommitted] = useState(initial);
  const validation = useSlqValidation(null, draft, dialect);
  const commit = (value: string) => {
    const next = value.trim();
    setCommitted(next);
    writeUrlState({ q: next || null });
  };
  return {
    draft,
    setDraft: (value: string) => {
      setDraft(value);
      if (value.trim() === "") commit("");
    },
    run: () => commit(draft),
    runQuery: (value: string) => {
      setDraft(value);
      commit(value);
    },
    probe:
      validation.status === SlqProbeStatus.valid && validation.query !== committed
        ? { ...validation, status: SlqProbeStatus.ready }
        : validation,
    active: committed !== "",
    committed,
    filterItems: (items) => items,
    resultItems: undefined,
    hasMore: false,
    loadMore: () => {},
    isLoadingMore: false,
  };
}
