import { useQuery } from "@tanstack/react-query";
import { projectSummaryQuery, projectsPageQuery, PROJECTS_PAGE_SIZE } from "./queries/projects";
import type { PermissionValue } from "./types";
import { useDirectory } from "./useDirectory";

/** Search all visible projects while retaining only one rendered page. `available`
 * is the UNFILTERED count (the summary), so an empty search page can still say
 * whether any project exists at all. */
export function useProjectDirectory(hideRelated = false, permission: PermissionValue | "" = "") {
  const summary = useQuery(projectSummaryQuery());
  const directory = useDirectory(
    JSON.stringify(["projects", hideRelated, permission]),
    PROJECTS_PAGE_SIZE,
    (q, page) => projectsPageQuery(q, page, hideRelated, permission),
  );
  return { ...directory, available: summary.data?.total ?? directory.total };
}
