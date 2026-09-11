import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Settings } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { usePageSpaceDirectory } from "../lib/usePageSpaceDirectory";
import { pageSpaceSummaryQuery } from "../lib/queries";
import { Permission } from "../lib/types";
import { Button } from "../components/Button";
import { DirectoryPager } from "../components/DirectoryPager";
import { EmptyState } from "../components/EmptyState";
import { ListSearchInput } from "../components/ListSearchInput";
import { Spinner } from "../components/Spinner";
import { QueryError } from "../components/QueryError";

/** The readable wiki directory; only one search window is mounted. */
export function PagesIndexPage() {
  const perms = usePermissions();
  const spaces = usePageSpaceDirectory();
  const summary = useQuery(pageSpaceSummaryQuery());
  const canManage = perms.anySpace(Permission.pageManage);
  return <div className="flex h-full flex-col">
    <header className="flex flex-wrap items-center gap-2 border-b border-subtle px-6 py-3.5">
      <BookOpen size={15} className="text-fg-muted" aria-hidden />
      <h1 className="text-sm font-semibold text-heading">Pages</h1>
      {canManage && <Link to={RoutePath.settingsPages} className="ml-auto flex items-center gap-1.5 rounded-md border border-strong px-2 py-1 text-xs text-fg hover:bg-elevated">
        <Settings size={12} aria-hidden />Manage spaces
      </Link>}
    </header>
    <div className="flex-1 overflow-y-auto p-6">
      <ListSearchInput className="mb-3" value={spaces.filter} onChange={spaces.setFilter}
        placeholder="Find spaces by name or slug…" total={summary.data?.total ?? spaces.total} matched={spaces.total} noun="spaces" />
      <div aria-busy={spaces.busy}>
        {spaces.isPending ? <Spinner label="Loading spaces…" /> : spaces.isError ? <div className="space-y-2">
          <QueryError label="page spaces" error={spaces.error} />
          <Button variant="secondary" onClick={() => void spaces.refetch()}>Retry spaces</Button>
        </div> : spaces.rows.length === 0 ? <EmptyState icon={BookOpen} message={spaces.filter.trim()
          ? `No spaces match “${spaces.filter.trim()}”.`
          : canManage ? "No page spaces yet — create the first one under Manage spaces."
            : "No page spaces yet — an admin can create the first one."} />
          : <ul aria-label="Page spaces" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {spaces.rows.map(space => <li key={space.id}>
              <Link to={RoutePath.pageSpace} params={{ spaceSlug: space.slug }} className="flex h-full min-w-0 flex-col gap-1 rounded-lg border border-subtle bg-surface/50 p-4 hover:border-strong hover:bg-surface">
                <span className="flex min-w-0 flex-wrap items-baseline gap-2">
                  <span className="min-w-0 break-words text-sm font-medium text-heading">{space.name}</span>
                  <span className="ml-auto shrink-0 text-[11px] text-fg-muted">{space.page_count} page{space.page_count === 1 ? "" : "s"}</span>
                </span>
                {space.description && <span className="break-words text-xs leading-relaxed text-fg-muted">{space.description}</span>}
              </Link>
            </li>)}
          </ul>}
      </div>
      <DirectoryPager {...spaces} onPage={spaces.setPage} label="page spaces" />
    </div>
  </div>;
}
