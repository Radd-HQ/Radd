import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { RoutePath } from "./constants";
import { useCurrentUser, useIsAuthenticated, usePermissions } from "./hooks";
import { pageSpaceSummaryQuery } from "@radd-plugin-ui/pages/queries";
import { dashboardSummaryQuery } from "@radd-plugin-ui/dashboards/queries";
import { Permission } from "./types";
import { projectSummaryQuery } from "@radd-plugin-ui/projects/directory-queries";

/**
 * ONE source of area visibility for the shell nav (RADD-843): the sidebar, the rail, the palette
 * and the pins bar. Presentation only — every area enforces its own authz. Built from lists the
 * shell already loads plus `/auth/me`'s `nav`; every unknown answers TRUE (a link, never a leak).
 */
interface NavFacts {
  projects: boolean;
  reports: boolean;
  timesheet: boolean;
  portal: boolean;
  docs: boolean;
  dashboards: boolean;
  /** The pin/palette predicate: may this path's area be offered? Unknown
   * paths (issues, views, plugin routes) are always offered. */
  forPath: (path: string) => boolean;
}

export function useNavFacts(): NavFacts {
  const me = useCurrentUser();
  const perms = usePermissions();
  // Spec 121: a visitor (the Anyone principal) gets the public projects and
  // nothing personal — these facts fail CLOSED for them, and the personal
  // summaries are not even asked for.
  const authenticated = useIsAuthenticated();
  const projects = useQuery(projectSummaryQuery());
  const spaces = useQuery(pageSpaceSummaryQuery()); // actor-safe since spec 121 §5
  const dashboards = useQuery({ ...dashboardSummaryQuery(), enabled: authenticated });

  const projectCount = projects.data?.total;
  const spaceCount = spaces.data?.total;
  const dashboardCount = dashboards.data?.total;
  const canManagePages = perms.anySpace(Permission.pageManage);
  const canCreateDashboard = perms.anyProject(Permission.dashboardCreate);
  const navTimesheet = me?.nav?.timesheet;
  const navPortal = me?.nav?.portal;

  return useMemo(() => {
    // undefined (still loading / older payload) fails OPEN.
    const known = (value: boolean | undefined) => value !== false;
    const facts = {
      projects: projectCount === undefined || projectCount > 0,
      reports: projectCount === undefined || projectCount > 0,
      timesheet: authenticated && known(navTimesheet),
      portal: authenticated && known(navPortal),
      docs: spaceCount === undefined || spaceCount > 0 || canManagePages,
      dashboards:
        authenticated && (dashboardCount === undefined || dashboardCount > 0 || canCreateDashboard),
    };
    const byPrefix: [string, boolean][] = [
      [RoutePath.starred, authenticated],
      [RoutePath.timesheet, facts.timesheet],
      [RoutePath.reports, facts.reports],
      [RoutePath.portal, facts.portal],
      [RoutePath.projects, facts.projects],
    ];
    return {
      ...facts,
      forPath: (path: string) => {
        for (const [prefix, allowed] of byPrefix) {
          if (path === prefix || path.startsWith(`${prefix}/`)) return allowed;
        }
        if (path.startsWith("/pages")) return facts.docs;
        if (path.startsWith("/dashboards")) return facts.dashboards;
        return true;
      },
    };
  }, [
    authenticated,
    projectCount,
    spaceCount,
    dashboardCount,
    canManagePages,
    canCreateDashboard,
    navTimesheet,
    navPortal,
  ]);
}
