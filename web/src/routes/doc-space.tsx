import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronRight } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { docPageQuery, docPagesQuery, docSpacesQuery } from "../lib/queries";
import { Permission } from "../lib/types";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { DocPageView } from "../components/docs/DocPageView";
import { PageTree } from "../components/docs/PageTree";
import { PublicBadge } from "../components/docs/PublicBadge";
import { QueryError } from "../components/QueryError";

/**
 * `/docs/$spaceId` (+ `/docs/$spaceId/$pageId`, the canonical page URL) —
 * two-pane wiki view (spec 43): the collapsible page tree beside the selected
 * page. With no page selected, a hint (or the empty-space CTA) shows instead.
 */
export function DocSpacePage() {
  const { spaceId = "", pageId } = useParams({ strict: false });
  const perms = usePermissions();
  const spaces = useQuery(docSpacesQuery());
  const pages = useQuery({ ...docPagesQuery(spaceId), enabled: spaceId !== "" });
  const page = useQuery({ ...docPageQuery(pageId ?? ""), enabled: Boolean(pageId) });

  if (spaces.isPending || pages.isPending) {
    return <Spinner label="Loading docs…" />;
  }
  const space = spaces.data?.find((entry) => entry.id === spaceId);
  if (pages.isError || !space) {
    return (
      <div className="p-6">
        {!space ? (
          <p className="text-sm text-red-400">Doc space not found.</p>
        ) : (
          <QueryError label="pages" error={pages.error} />
        )}
      </div>
    );
  }

  const canWrite = perms.global(Permission.docWrite);
  const canManage = perms.global(Permission.docManage);
  const rows = pages.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-1.5 border-b border-subtle px-5 py-3 text-sm">
        <Link
          to={RoutePath.docs}
          className="flex items-center gap-1.5 text-fg-secondary hover:text-fg"
        >
          <BookOpen size={14} aria-hidden />
          Docs
        </Link>
        <ChevronRight size={13} className="text-fg-faint" aria-hidden />
        <Link
          to={RoutePath.docSpace}
          params={{ spaceId }}
          className="font-medium text-heading hover:underline"
        >
          {space.name}
        </Link>
        {space.public && <PublicBadge />}
        {page.data?.breadcrumb.map((crumb) => (
          <span key={crumb.id} className="flex min-w-0 items-center gap-1.5">
            <ChevronRight size={13} className="shrink-0 text-fg-faint" aria-hidden />
            <Link
              to={RoutePath.docPage}
              params={{ spaceId, pageId: crumb.id }}
              className="truncate text-fg-secondary hover:text-fg"
            >
              {crumb.title}
            </Link>
          </span>
        ))}
      </header>

      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Page tree"
          className="w-64 shrink-0 overflow-y-auto border-r border-subtle p-2"
        >
          <PageTree spaceId={spaceId} rows={rows} selectedId={pageId} canWrite={canWrite} />
        </nav>

        <div className="min-w-0 flex-1 overflow-y-auto">
          {pageId ? (
            page.isPending ? (
              <Spinner label="Loading page…" />
            ) : page.isError ? (
              <div className="p-6">
                <QueryError label="page" error={page.error} />
              </div>
            ) : (
              <DocPageView
                key={page.data.id}
                page={page.data}
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
