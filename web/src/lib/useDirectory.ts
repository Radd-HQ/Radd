import { useState } from "react";
import { useQuery, type QueryKey, type UseQueryOptions } from "@tanstack/react-query";
import type { Paged } from "./api";
import { SEARCH_DEBOUNCE_MS } from "./constants";
import { useDebounced } from "./hooks";

export interface DirectoryOptions {
  /** Spec 121: a caller may hold the directory back (a visitor has no dashboards);
   * a factory's own `enabled` still counts. */
  enabled?: boolean;
  /** Seed the search box (a picker opened from a typed prefix). */
  initialFilter?: string;
}

/** Bounded search window shared by directory consumers; scope changes reset paging. */
export function useDirectory<T, K extends QueryKey>(scope: string, pageSize: number, factory: (q: string, page: number) => UseQueryOptions<Paged<T>, Error, Paged<T>, K>, { enabled = true, initialFilter = "" }: DirectoryOptions = {}) {
  const [filter, setFilter] = useState(initialFilter);
  const q = useDebounced(filter.trim(), SEARCH_DEBOUNCE_MS);
  const identity = JSON.stringify([scope, q]);
  const [position, setPosition] = useState({ identity, page: 0 });
  if (position.identity !== identity) setPosition({ identity, page: 0 });
  const page = position.identity === identity ? position.page : 0;
  const queryOptions = factory(q, page);
  const query = useQuery({ ...queryOptions, enabled: enabled && (queryOptions.enabled ?? true) });
  return { ...query, filter, setFilter, q, page, rows: query.data?.rows ?? [], total: query.data?.total ?? 0,
    pageSize, busy: query.isFetching || filter.trim() !== q,
    setPage: (next: number) => setPosition({ identity, page: Math.max(0, next) }) };
}
