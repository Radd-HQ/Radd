import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Settings } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { useListFilter } from "../lib/list-filter";
import { pageSpacesQuery } from "../lib/queries";
import { Permission } from "../lib/types";
import { EmptyState } from "../components/EmptyState";
import { ListSearchInput } from "../components/ListSearchInput";
import { Spinner } from "../components/Spinner";
import { QueryError } from "../components/QueryError";
/** `/docs` — Pages's spaces index (spec 43): name, description, page count. */
export function PagesIndexPage() {
  const perms = usePermissions();
  const spaces = useQuery(pageSpacesQuery());
  // Hooks run before the pending/error early returns to keep the order stable.
  const all = spaces.data ?? [];
  const search = useListFilter(all, (space) => [space.name, space.slug]);
  const list = search.filtered;

  if (spaces.isPending) return <Spinner label="Loading docs…" />;
  if (spaces.isError) {
    return (
      <div className="p-6">
        <QueryError label="page spaces" error={spaces.error} />
      </div>
    );
  }

  // deliberately-global: gates CREATING a space, which `create_space` checks
  // with no space id (RADD-810) — not a per-space question.
  const canManage = perms.global(Permission.pageManage);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-subtle px-6 py-3.5">
        <BookOpen size={15} className="text-fg-muted" aria-hidden />
        <h1 className="text-sm font-semibold text-heading">Pages</h1>
        {canManage && (
          <Link
            to={RoutePath.settingsPages}
            className="ml-auto flex items-center gap-1.5 rounded-md border border-strong px-2 py-1 text-xs text-fg hover:bg-elevated"
          >
            <Settings size={12} aria-hidden />
            Manage spaces
          </Link>
        )}
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {all.length === 0 ? (
          <EmptyState
            icon={BookOpen}
            message={
              canManage
                ? "No page spaces yet — create the first one under Manage spaces."
                : "No page spaces yet — an admin can create the first one."
            }
          />
        ) : (
          <>
            {all.length > 8 && (
              <ListSearchInput
                className="mb-3"
                value={search.filter}
                onChange={search.setFilter}
                placeholder="Filter spaces by name or slug…"
                total={all.length}
                matched={list.length}
                noun="spaces"
              />
            )}
            {list.length === 0 ? (
              <EmptyState
                icon={BookOpen}
                message={`No spaces match “${search.filter.trim()}”.`}
              />
            ) : (
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {list.map((space) => (
                  <li key={space.id}>
                    <Link
                      to={RoutePath.pageSpace}
                      params={{ spaceSlug: space.slug }}
                      className="flex h-full flex-col gap-1 rounded-lg border border-subtle bg-surface/50 p-4 hover:border-strong hover:bg-surface"
                    >
                      <span className="flex items-baseline gap-2">
                        <span className="text-sm font-medium text-heading">{space.name}</span>
                        <span className="ml-auto shrink-0 text-[11px] text-fg-muted">
                          {space.page_count} page{space.page_count === 1 ? "" : "s"}
                        </span>
                      </span>
                      {space.description && (
                        <span className="text-xs leading-relaxed text-fg-muted">
                          {space.description}
                        </span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}
