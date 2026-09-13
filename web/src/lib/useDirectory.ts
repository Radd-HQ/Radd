import { useState } from "react";
import { useQuery, type QueryKey, type UseQueryOptions } from "@tanstack/react-query";
import type { Paged } from "./api";
import { SEARCH_DEBOUNCE_MS } from "./constants";
import { useDebounced } from "./hooks";

/** Bounded search window shared by directory consumers; scope changes reset paging. */
export function useDirectory<T, K extends QueryKey>(scope: string, pageSize: number, factory: (q: string, page: number) => UseQueryOptions<Paged<T>, Error, Paged<T>, K>, enabled = true) {
  const [filter, setFilter] = useState("");
  const q = useDebounced(filter.trim(), SEARCH_DEBOUNCE_MS);
  const identity = JSON.stringify([scope, q]);
  const [position, setPosition] = useState({ identity, page: 0 });
  if (position.identity !== identity) setPosition({ identity, page: 0 });
  const page = position.identity === identity ? position.page : 0;
  // Spec 121: a caller may hold the directory back (a visitor has no dashboards);
  // a factory's own `enabled` still counts.
  const options = factory(q, page);
  const query = useQuery({ ...options, enabled: enabled && (options.enabled ?? true) });
  return { ...query, filter, setFilter, q, page, rows: query.data?.rows ?? [], total: query.data?.total ?? 0,
    pageSize, busy: query.isFetching || filter.trim() !== q,
    setPage: (next: number) => setPosition({ identity, page: Math.max(0, next) }) };
}

