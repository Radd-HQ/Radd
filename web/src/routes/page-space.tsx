import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { BookOpen, ChevronRight } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { pageByPathQuery, pagesQuery, pageSpacesQuery } from "../lib/queries";
import { Permission } from "../lib/types";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { PageView } from "../components/pages/PageView";
import { BreadcrumbCrumb } from "../components/pages/BreadcrumbCrumb";
import { PageTree } from "../components/pages/PageTree";
import { PublicBadge } from "../components/pages/PublicBadge";
import { QueryError } from "../components/QueryError";

/**
 * `/pages/$spaceSlug` (+ `/pages/$spaceSlug/$pageSlug`) — the two-pane pages
 * view (spec 43): the collapsible tree beside the selected page.
 *
 * Both segments address by slug OR id (RADD-702), which is what makes the URL
 * migration free: a pre-702 `/docs/<uuid>/<uuid>` link, a search result that
 * only knows ids, and a hand-typed `/pages/handbook/onboarding` all land here,
 * and the effect below rewrites the address bar to the canonical slug form. It
 * REPLACES the history entry — arriving by an old link shouldn't cost the
 * visitor a Back press to escape.
 */
export function PageSpacePage() {
  const { spaceSlug = "", pageSlug } = useParams({ strict: false });
  const navigate = useNavigate();
  const perms = usePermissions();
  const spaces = useQuery(pageSpacesQuery());
  const space = spaces.data?.find(
    (entry) => entry.slug === spaceSlug || entry.id === spaceSlug,
  );
  const pages = useQuery({ ...pagesQuery(space?.id ?? ""), enabled: Boolean(space) });
  const page = useQuery({
    ...pageByPathQuery(spaceSlug, pageSlug ?? ""),
    enabled: Boolean(spaceSlug) && Boolean(pageSlug),
  });

  const canonicalSpace = space?.slug;
  const canonicalPage = page.data?.slug;
  useEffect(() => {
    if (!canonicalSpace) return;
    const spaceOff = canonicalSpace !== spaceSlug;
    const pageOff = Boolean(pageSlug) && Boolean(canonicalPage) && canonicalPage !== pageSlug;
    if (!spaceOff && !pageOff) return;
    void navigate({
      to: pageSlug ? RoutePath.page : RoutePath.pageSpace,
      params: pageSlug
        ? { spaceSlug: canonicalSpace, pageSlug: canonicalPage ?? pageSlug }
        : { spaceSlug: canonicalSpace },
      replace: true,
    });
  }, [canonicalSpace, canonicalPage, spaceSlug, pageSlug, navigate]);

  if (spaces.isPending || (Boolean(space) && pages.isPending)) {
    return <Spinner label="Loading pages…" />;
  }
  if (pages.isError || !space) {
    return (
      <div className="p-6">
        {!space ? (
          <p className="text-sm text-red-400">Page space not found.</p>
        ) : (
          <QueryError label="pages" error={pages.error} />
        )}
      </div>
    );
  }

  const canWrite = perms.global(Permission.pageWrite);
  const canManage = perms.global(Permission.pageManage);
  const rows = pages.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-1.5 border-b border-subtle px-5 py-3 text-sm">
        <Link
          to={RoutePath.pages}
          className="flex items-center gap-1.5 text-fg-secondary hover:text-fg"
        >
          <BookOpen size={14} aria-hidden />
          Pages
        </Link>
        <ChevronRight size={13} className="text-fg-faint" aria-hidden />
        <Link
          to={RoutePath.pageSpace}
          params={{ spaceSlug: space.slug }}
          className="font-medium text-heading hover:underline"
        >
          {space.name}
        </Link>
        {space.public && <PublicBadge />}
        {page.data?.breadcrumb.map((crumb) => (
          <span key={crumb.id} className="flex min-w-0 items-center gap-1.5">
            <ChevronRight size={13} className="shrink-0 text-fg-faint" aria-hidden />
            {/* RADD-714: each ancestor carries its siblings, so moving sideways
                does not mean hunting in the tree. */}
            <BreadcrumbCrumb crumb={crumb} spaceId={space.id} spaceSlug={space.slug} />
          </span>
        ))}
      </header>

      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Page tree"
          className="w-64 shrink-0 overflow-y-auto border-r border-subtle p-2"
        >
          <PageTree
            spaceId={space.id}
            spaceSlug={space.slug}
            rows={rows}
            selectedId={page.data?.id}
            canWrite={canWrite}
          />
        </nav>

        <div className="min-w-0 flex-1 overflow-y-auto">
          {pageSlug ? (
            page.isPending ? (
              <Spinner label="Loading page…" />
            ) : page.isError ? (
              <div className="p-6">
                <QueryError label="page" error={page.error} />
              </div>
            ) : (
              <PageView
                key={page.data.id}
                page={page.data}
                spaceSlug={space.slug}
                canWrite={canWrite}
                canManage={canManage}
              />
            )
          ) : (
            <div className="p-6">
              <EmptyState
                icon={BookOpen}
                message={
                  rows.length === 0
                    ? canWrite
                      ? "This space has no pages yet — create the first one."
                      : "This space has no pages yet."
                    : "Select a page from the tree."
                }
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
