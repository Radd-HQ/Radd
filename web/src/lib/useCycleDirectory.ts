import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SEARCH_DEBOUNCE_MS } from "./constants";
import { useDebounced } from "./hooks";
import { cyclesPageQuery, CYCLES_PAGE_SIZE } from "./queries/cycles";
import type { CycleStatusValue } from "./types";

/** One visible cycle window; filters never operate on a truncated local list. */
export function useCycleDirectory({ status, includeCompleted = true, excludeId = "", initialFilter = "", datedOnly = false }: {
  status?: CycleStatusValue; includeCompleted?: boolean; excludeId?: string; initialFilter?: string;
  datedOnly?: boolean;
} = {}) {
  const [filter, setFilter] = useState(initialFilter);
  const q = useDebounced(filter.trim(), SEARCH_DEBOUNCE_MS);
  const scope = JSON.stringify([q, status, includeCompleted, excludeId, datedOnly]);
  const [position, setPosition] = useState({ scope, page: 0 });
  if (position.scope !== scope) setPosition({ scope, page: 0 });
  const page = position.scope === scope ? position.page : 0;
  const query = useQuery(cyclesPageQuery(q, page, status, includeCompleted, excludeId, datedOnly));
  return {
    ...query, filter, setFilter, page, q,
    rows: query.data?.rows ?? [], total: query.data?.total ?? 0,
    busy: query.isFetching || q !== filter.trim(), pageSize: CYCLES_PAGE_SIZE,
    setPage: (next: number) => setPosition({ scope, page: Math.max(0, next) }),
  };
}
