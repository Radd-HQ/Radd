import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SEARCH_DEBOUNCE_MS } from "./constants";
import { useDebounced } from "./hooks";
import { projectSummaryQuery, projectsPageQuery, PROJECTS_PAGE_SIZE } from "./queries/projects";
import type { PermissionValue } from "./types";

/** Search all visible projects while retaining only one rendered page. */
export function useProjectDirectory(hideRelated = false, permission: PermissionValue | "" = "") {
  const [filter, setFilter] = useState("");
  const q = useDebounced(filter.trim(), SEARCH_DEBOUNCE_MS);
  const scope = JSON.stringify([q, hideRelated, permission]);
  const [position, setPosition] = useState({ scope, page: 0 });
  if (position.scope !== scope) setPosition({ scope, page: 0 });
  const page = position.scope === scope ? position.page : 0;
  const summary = useQuery(projectSummaryQuery());
  const query = useQuery(projectsPageQuery(q, page, hideRelated, permission));
  return {
    ...query, filter, setFilter, page,
    rows: query.data?.rows ?? [],
    total: query.data?.total ?? 0,
    available: summary.data?.total ?? query.data?.total ?? 0,
    busy: query.isFetching || q !== filter.trim(),
    pageSize: PROJECTS_PAGE_SIZE,
    setPage: (next: number) => setPosition({ scope, page: Math.max(0, next) }),
  };
}
