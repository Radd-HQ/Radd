import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { RoutePath } from "./constants";
import { useCurrentUser, usePermissions } from "./hooks";
import { dashboardsQuery, pageSpacesQuery, projectsQuery } from "./queries";
import { Permission } from "./types";

/**
 * ONE source of area visibility for the shell nav (RADD-843), consumed by the
 * Sidebar, the collapsed rail, the command palette and the pins bar — four
 * surfaces, one truth, so the rail can never drift from the sidebar again.
 *
 * Hiding is presentation: every area still enforces its own authz on direct
 * navigation. Facts come from lists the shell already loads (zero extra
 * requests) plus two server booleans on the /auth/me payload (`nav`), and
 * every unknown answers TRUE — failing open here costs a link, never a leak.
 */
export interface NavFacts {
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
  const projects = useQuery(projectsQuery());
  const spaces = useQuery(pageSpacesQuery());
  const dashboards = useQuery(dashboardsQuery());

  const projectCount = projects.data?.length;
  const spaceCount = spaces.data?.length;
  const dashboardCount = dashboards.data?.length;
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
      timesheet: known(navTimesheet),
      portal: known(navPortal),
      docs: spaceCount === undefined || spaceCount > 0 || canManagePages,
      dashboards:
        dashboardCount === undefined || dashboardCount > 0 || canCreateDashboard,
    };
    const byPrefix: [string, boolean][] = [
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
    projectCount,
    spaceCount,
    dashboardCount,
    canManagePages,
    canCreateDashboard,
    navTimesheet,
    navPortal,
  ]);
}
