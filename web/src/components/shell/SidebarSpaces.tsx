import { useIsAuthenticated } from "../../lib/hooks";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Settings } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { pageSpaceByIdentityQuery, pageSpaceSummaryQuery } from "../../lib/queries";
import { usePageSpaceDirectory } from "../../lib/usePageSpaceDirectory";
import { SidebarDirectory } from "./SidebarDirectory";
import { navLinkClasses, SectionHeader } from "./SidebarRows";

/** Bounded wiki navigation keeps the current space visible outside its window. */
export function SidebarSpaces({ collapsed, onToggle, canManage }: {
  collapsed: boolean; onToggle: () => void; canManage: boolean;
}) {
  const summary = useQuery({ ...pageSpaceSummaryQuery(), enabled: useIsAuthenticated() });
  const directory = usePageSpaceDirectory(!collapsed && useIsAuthenticated());
  const { spaceSlug = "" } = useParams({ strict: false });
  const current = useQuery(pageSpaceByIdentityQuery(spaceSlug));
  if (!summary.isError && (summary.data?.total ?? 0) === 0 && !canManage) return null;
  const outsideWindow = current.data && !directory.rows.some(row => row.id === current.data?.id);
  return <div className="mt-3">
    <SectionHeader label="Pages" labelTo={RoutePath.pages} collapsed={collapsed} onToggle={onToggle}
      actions={canManage && <Link to={RoutePath.settingsPages} aria-label="Manage page spaces" title="Manage page spaces"
        className="ml-auto rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus">
        <Settings size={12} aria-hidden />
      </Link>} />
    {!collapsed && <SidebarDirectory directory={directory} label="wiki spaces">
      {outsideWindow && current.data && <div aria-label="Current wiki space" className="mb-1 border-b border-subtle pb-1">
        <span className="px-2 text-[10px] text-fg-muted">Current space</span>
        <Link to={RoutePath.pageSpace} params={{ spaceSlug: current.data.slug }} className={navLinkClasses}>
          <BookOpen size={14} aria-hidden /><span className="truncate">{current.data.name}</span>
        </Link>
      </div>}
      {directory.isPending ? <p className="px-2 py-1 text-xs text-fg-muted">Loading spaces…</p>
        : directory.rows.length === 0 && !directory.filter ? <p className="px-2 pb-1 text-xs text-fg-faint">No spaces yet.</p>
          : <ul>{directory.rows.map(space => <li key={space.id}>
            <Link to={RoutePath.pageSpace} params={{ spaceSlug: space.slug }} className={navLinkClasses}>
              <BookOpen size={14} aria-hidden /><span className="truncate">{space.name}</span>
            </Link>
          </li>)}</ul>}
    </SidebarDirectory>}
  </div>;
}
