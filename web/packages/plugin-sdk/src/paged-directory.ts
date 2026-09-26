import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { Paged } from "./api";

export interface PagedDirectoryQuery<T> {
  queryKey: readonly unknown[];
  queryFn: (context: { signal: AbortSignal }) => Promise<Paged<T>>;
  meta?: Record<string, unknown>;
  /** Hold the directory back (a folded sidebar section). */
  enabled?: boolean;
}
/** Search + bounded paging over a provider's directory; the provider owns data and scope. Pages
 * are shared across consumers and the previous page stays up while the next loads (RADD-1373). */
export function usePagedDirectory<T>(scope: string, query: (q: string, page: number, pageSize: number) => PagedDirectoryQuery<T>, { pageSize = 50, initialFilter = "", enabled = true } = {}) {
  const [filter, setFilter] = useState(initialFilter);
  const [q, setQ] = useState(initialFilter.trim());
  useEffect(() => { const timer = setTimeout(() => setQ(filter.trim()), 150); return () => clearTimeout(timer); }, [filter]);
  const identity = JSON.stringify([scope, q]);
  const [position, setPosition] = useState({ identity, page: 0 });
  if (position.identity !== identity) setPosition({ identity, page: 0 });
  const page = position.identity === identity ? position.page : 0;
  const definition = query(q, page, pageSize);
  // `enabled`: a caller may hold the directory back (a visitor has no dashboards).
  const result = useQuery({ ...definition, enabled, staleTime: 30_000, placeholderData: keepPreviousData });
  return { ...result, filter, setFilter, q, page, pageSize, rows: result.data?.rows ?? [], total: result.data?.total ?? 0,
    busy: result.isFetching || q !== filter.trim(), setPage: (next: number) => setPosition({ identity, page: Math.max(0, next) }) };
}
