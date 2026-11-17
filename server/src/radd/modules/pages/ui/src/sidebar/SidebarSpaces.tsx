import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Settings } from "lucide-react";
import { SidebarLink, SidebarSection } from "@radd/plugin-sdk";
import { PageRoute, spacesSettingsLink } from "../links";
import { pageSpaceByIdentityQuery, pageSpaceSummaryQuery } from "../queries";
import { usePageSpaceDirectory } from "../directory";
import { PagePermission, useSpacePermissions } from "../permissions";

/** How many spaces the section lists before "Show all". */
const SPACES_SHOWN = 8;

/** The sidebar's Pages section (the `sidebar.section` slot, "pages"): bounded wiki navigation that
 *  keeps the current space visible outside its window. The fold is the host's sidebar preference. */
export function SidebarSpaces({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const summary = useQuery(pageSpaceSummaryQuery());
  const [showAll, setShowAll] = useState(false);
  const canManage = useSpacePermissions().anySpace(PagePermission.manage);
  const directory = usePageSpaceDirectory(!collapsed);
  const { spaceSlug = "" } = useParams({ strict: false }) as { spaceSlug?: string };
  const current = useQuery(pageSpaceByIdentityQuery(spaceSlug));
  if (!summary.isError && (summary.data?.total ?? 0) === 0 && !canManage) return null;
  // A short list until asked (RADD-1559): the directory hands over up to fifty
  // spaces, and fifty rows here pushed Cycles and Projects off the screen. A
  // filter shows everything it matched; the current space is always kept.
  const shown = showAll || directory.filter ? directory.rows : directory.rows.slice(0, SPACES_SHOWN);
  const more = (directory.total ?? directory.rows.length) - shown.length;
  const outsideWindow = current.data && !shown.some(row => row.id === current.data?.id);
  return <SidebarSection label="Pages" labelTo={PageRoute.pages} collapsed={collapsed} onToggle={onToggle}
    directory={directory} directoryLabel="wiki spaces"
    actions={canManage && <Link {...spacesSettingsLink} aria-label="Manage page spaces" title="Manage page spaces"
      className="ml-auto rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus">
      <Settings size={12} aria-hidden />
    </Link>}>
    {outsideWindow && current.data && <div aria-label="Current wiki space" className="mb-1 border-b border-subtle pb-1">
      <span className="px-2 text-micro text-fg-muted">Current space</span>
      <SidebarLink to={PageRoute.space} params={{ spaceSlug: current.data.slug }}>
        <BookOpen size={14} aria-hidden /><span className="truncate">{current.data.name}</span>
      </SidebarLink>
    </div>}
    {directory.isPending ? <p className="px-2 py-1 text-xs text-fg-muted">Loading spaces…</p>
      : directory.rows.length === 0 && !directory.filter ? <p className="px-2 pb-1 text-xs text-fg-faint">No spaces yet.</p>
        : <ul data-sidebar-spaces>{shown.map(space => <li key={space.id}>
          <SidebarLink to={PageRoute.space} params={{ spaceSlug: space.slug }}>
            <BookOpen size={14} aria-hidden /><span className="truncate">{space.name}</span>
          </SidebarLink>
        </li>)}
        {!directory.filter && directory.rows.length > SPACES_SHOWN && <li>
          <button type="button" onClick={() => setShowAll(value => !value)} aria-expanded={showAll} data-spaces-toggle
            className="w-full rounded px-2 py-1 text-left text-xs text-fg-muted hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus cursor-pointer">
            {showAll ? "Show fewer" : `Show all ${(shown.length + more).toLocaleString()}`}
          </button>
        </li>}</ul>}
  </SidebarSection>;
}
