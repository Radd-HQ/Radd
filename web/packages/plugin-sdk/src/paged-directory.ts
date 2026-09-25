import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Paged } from "./api";

export interface PagedDirectoryQuery<T> {
  queryKey: readonly unknown[];
  queryFn: (context: { signal: AbortSignal }) => Promise<Paged<T>>;
  meta?: Record<string, unknown>;
}
/** A mounted directory owns its request/cache lifetime; its provider owns data and scope. */
export function usePagedDirectory<T>(scope: string, query: (q: string, page: number, pageSize: number) => PagedDirectoryQuery<T>, { pageSize = 50, initialFilter = "" } = {}) {
  const session = useId();
  const [filter, setFilter] = useState(initialFilter);
  const [q, setQ] = useState(initialFilter.trim());
  useEffect(() => { const timer = setTimeout(() => setQ(filter.trim()), 150); return () => clearTimeout(timer); }, [filter]);
  const identity = JSON.stringify([scope, q]);
  const [position, setPosition] = useState({ identity, page: 0 });
  if (position.identity !== identity) setPosition({ identity, page: 0 });
  const page = position.identity === identity ? position.page : 0;
  const definition = query(q, page, pageSize);
  const result = useQuery({ ...definition, queryKey: [...definition.queryKey, session], gcTime: 0, staleTime: 0, retry: false });
  return { ...result, filter, setFilter, q, page, pageSize, rows: result.data?.rows ?? [], total: result.data?.total ?? 0,
    busy: result.isFetching || q !== filter.trim(), setPage: (next: number) => setPosition({ identity, page: Math.max(0, next) }) };
}
