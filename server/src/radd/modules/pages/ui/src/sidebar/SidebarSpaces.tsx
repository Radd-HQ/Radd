import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Settings } from "lucide-react";
import { SidebarLink, SidebarSection } from "@radd/plugin-sdk";
import { PageRoute, spacesSettingsLink } from "../links";
import { pageSpaceByIdentityQuery, pageSpaceSummaryQuery } from "../queries";
import { usePageSpaceDirectory } from "../directory";
import { PagePermission, useSpacePermissions } from "../permissions";

/** The sidebar's Pages section (the `sidebar.section` slot, "pages"): bounded wiki navigation that
 *  keeps the current space visible outside its window. The fold is the host's sidebar preference. */
export function SidebarSpaces({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const summary = useQuery(pageSpaceSummaryQuery());
  const canManage = useSpacePermissions().anySpace(PagePermission.manage);
  const directory = usePageSpaceDirectory(!collapsed);
  const { spaceSlug = "" } = useParams({ strict: false }) as { spaceSlug?: string };
  const current = useQuery(pageSpaceByIdentityQuery(spaceSlug));
  if (!summary.isError && (summary.data?.total ?? 0) === 0 && !canManage) return null;
  const outsideWindow = current.data && !directory.rows.some(row => row.id === current.data?.id);
  return <SidebarSection label="Pages" labelTo={PageRoute.pages} collapsed={collapsed} onToggle={onToggle}
    directory={directory} directoryLabel="wiki spaces"
    actions={canManage && <Link {...spacesSettingsLink} aria-label="Manage page spaces" title="Manage page spaces"
      className="ml-auto rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus">
      <Settings size={12} aria-hidden />
    </Link>}>
    {outsideWindow && current.data && <div aria-label="Current wiki space" className="mb-1 border-b border-subtle pb-1">
      <span className="px-2 text-[10px] text-fg-muted">Current space</span>
      <SidebarLink to={PageRoute.space} params={{ spaceSlug: current.data.slug }}>
        <BookOpen size={14} aria-hidden /><span className="truncate">{current.data.name}</span>
      </SidebarLink>
    </div>}
    {directory.isPending ? <p className="px-2 py-1 text-xs text-fg-muted">Loading spaces…</p>
      : directory.rows.length === 0 && !directory.filter ? <p className="px-2 pb-1 text-xs text-fg-faint">No spaces yet.</p>
        : <ul>{directory.rows.map(space => <li key={space.id}>
          <SidebarLink to={PageRoute.space} params={{ spaceSlug: space.slug }}>
            <BookOpen size={14} aria-hidden /><span className="truncate">{space.name}</span>
          </SidebarLink>
        </li>)}</ul>}
  </SidebarSection>;
}
