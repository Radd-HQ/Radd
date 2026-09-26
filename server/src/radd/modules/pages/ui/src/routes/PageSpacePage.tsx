import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Archive, BookOpen, ChevronRight } from "lucide-react";
import { Button, EmptyState, ErrorText, Modal, QueryError, ReadingPane } from "@radd/plugin-sdk";
import { PageRoute, pageLink } from "../links";
import { archivedPagesQuery, pageByKeyQuery, pageByPathQuery, pagesQuery, pageSpaceByIdentityQuery } from "../queries";
import { PagePermission, useSpacePermissions } from "../permissions";
import { Loading } from "../view/Loading";
import { PageView } from "../view/PageView";
import { BreadcrumbCrumb } from "../view/BreadcrumbCrumb";
import { PageTree } from "../view/PageTree";
import { ArchivedPagesPanel } from "../view/ArchivedPagesPanel";
import { archivedRows } from "../view/archived-rows";
import { PublicBadge } from "../view/PublicBadge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** `/pages/$spaceSlug[/<path…>]` — the tree beside the selected page (spec 43). The page segment is a
 *  PATH (RADD-1233); an id, a number or a stale path also resolves, and the effect below REPLACES the
 *  URL with the canonical one the answer carries. */
export function PageSpacePage() {
  const { spaceSlug = "", _splat: pagePath = "" } = useParams({ strict: false }) as {
    spaceSlug?: string;
    _splat?: string;
  };
  // The tree's `selectedId` and every effect below key on "is a page open".
  const pageSlug = pagePath || undefined;
  // `?archived=1` (RADD-1228): the archive browser in place of a page.
  const { archived: browsingArchive = false } = useSearch({ strict: false }) as { archived?: boolean };
  const navigate = useNavigate();
  const perms = useSpacePermissions();
  const spaceQuery = useQuery(pageSpaceByIdentityQuery(spaceSlug));
  const space = spaceQuery.data;
  // RADD-1240: a /pages/<uuid> no space owns may name a PAGE — land on it.
  const segmentIsId = UUID.test(spaceSlug);
  const rescue = useQuery({
    ...pageByKeyQuery(spaceSlug),
    enabled: segmentIsId && spaceQuery.data === null,
  });
  useEffect(() => {
    if (!rescue.data) return;
    void navigate({ ...pageLink(rescue.data.space.slug, rescue.data.path), replace: true });
  }, [rescue.data, navigate]);
  const [treeOpen, setTreeOpen] = useState(false);
  useEffect(() => setTreeOpen(false), [spaceSlug, pageSlug]);
  const pages = useQuery({ ...pagesQuery(space?.id ?? ""), enabled: Boolean(space) });
  // The archive is a `page.manage` listing on the server; asking without the
  // atom would be a 403 in the console on every visit, so it is gated here too.
  const canBrowseArchive = Boolean(space) && perms.space(space!, PagePermission.manage);
  const archive = useQuery({ ...archivedPagesQuery(space?.id ?? ""), enabled: canBrowseArchive });
  const archivedCount = archive.data ? archivedRows(archive.data).length : 0;
  const page = useQuery({
    ...pageByPathQuery(spaceSlug, pagePath),
    enabled: Boolean(spaceSlug) && Boolean(pageSlug),
  });

  const canonicalSpace = space?.slug;
  const canonicalPage = page.data?.path;
  useEffect(() => {
    if (!canonicalSpace) return;
    const spaceOff = canonicalSpace !== spaceSlug;
    const pageOff = Boolean(pageSlug) && Boolean(canonicalPage) && canonicalPage !== pagePath;
    if (!spaceOff && !pageOff) return;
    if (pageSlug) {
      void navigate({ ...pageLink(canonicalSpace, canonicalPage ?? pagePath), replace: true });
    } else {
      void navigate({ to: PageRoute.space, params: { spaceSlug: canonicalSpace }, replace: true });
    }
  }, [canonicalSpace, canonicalPage, spaceSlug, pageSlug, pagePath, navigate]);

  if (spaceQuery.isPending || (Boolean(space) && pages.isPending)) {
    return <Loading label="Loading pages…" />;
  }
  if (spaceQuery.isError) return <div className="space-y-2 p-6">
    <QueryError label="page space" error={spaceQuery.error} />
    <Button variant="secondary" onClick={() => void spaceQuery.refetch()}>Retry space</Button>
  </div>;
  if (segmentIsId && !space && (rescue.isPending || rescue.data)) {
    return <Loading label="Opening page…" />;
  }
  if (pages.isError || !space) {
    return (
      <div className="space-y-3 p-6">
        {!space ? (
          <>
            <ErrorText size="sm" error={`Page space not found: ${spaceSlug}`} />
            <p className="text-[13px] text-fg-muted">
              A page address is <code>/pages/&lt;space&gt;/&lt;page&gt;</code>, or{" "}
              <code>/pages?pageId=&lt;number&gt;</code> for a permalink.{" "}
              <Link to={PageRoute.pages} className="text-accent-text underline-offset-2 hover:underline">
                All spaces
              </Link>
            </p>
          </>
        ) : (
          <QueryError label="pages" error={pages.error} />
        )}
      </div>
    );
  }

  // All three resolve at SPACE scope (RADD-810); commenting is its own atom, comment.write (RADD-770).
  const canWrite = perms.space(space, PagePermission.write);
  const canManage = perms.space(space, PagePermission.manage);
  const canComment = perms.space(space, PagePermission.commentWrite);
  const rows = pages.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="flex min-w-0 flex-wrap items-center gap-1.5 border-b border-subtle px-5 py-3 text-sm">
        <Link
          to={PageRoute.pages}
          className="flex items-center gap-1.5 text-fg-secondary hover:text-fg"
        >
          <BookOpen size={14} aria-hidden />
          Pages
        </Link>
        <ChevronRight size={13} className="text-fg-faint" aria-hidden />
        <Link
          to={PageRoute.space}
          params={{ spaceSlug: space.slug }}
          className="min-w-0 break-words font-medium text-heading hover:underline"
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

      <div className="px-3 py-2 lg:hidden">
        <Button variant="secondary" aria-haspopup="dialog" onClick={() => setTreeOpen(true)}>Browse pages</Button>
      </div>
      {treeOpen && <Modal title="Pages in this space" onClose={() => setTreeOpen(false)}>
        <div onClick={event => { if ((event.target as HTMLElement).closest("a")) setTreeOpen(false); }}>
          <PageTree spaceId={space.id} spaceSlug={space.slug} rows={rows} selectedId={page.data?.id} canWrite={canWrite} />
        </div>
      </Modal>}
      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Page tree"
          className="hidden w-64 shrink-0 overflow-y-auto border-r border-subtle p-2 lg:block"
        >
          <PageTree
            spaceId={space.id}
            spaceSlug={space.slug}
            rows={rows}
            selectedId={page.data?.id}
            canWrite={canWrite}
          />
          {canBrowseArchive && (
            <Link
              to={PageRoute.space}
              params={{ spaceSlug: space.slug }}
              search={{ archived: true }}
              data-archived-pages-link
              aria-current={browsingArchive && !pageSlug ? "page" : undefined}
              className={
                "mt-3 flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs " +
                (browsingArchive && !pageSlug
                  ? "bg-elevated text-heading"
                  : "text-fg-muted hover:bg-elevated/60 hover:text-fg")
              }
            >
              <Archive size={12} aria-hidden />
              Archived pages
              {archivedCount > 0 && (
                <span className="ml-auto rounded bg-elevated px-1 font-mono text-[10px] text-fg-faint">
                  {archivedCount}
                </span>
              )}
            </Link>
          )}
        </nav>

        {/* `@container/page` so the reading pane's `@4xl:` variants have something
            to query — without a container ancestor those rules never match, and the
            panel would silently stay stacked at every width (same wrapper the
            issue route carries). */}
        <div className="@container/page min-w-0 flex-1 overflow-y-auto">
          {pageSlug ? (
            page.isPending ? (
              <Loading label="Loading page…" />
            ) : page.isError ? (
              <div className="p-6">
                <QueryError label="page" error={page.error} />
              </div>
            ) : (
              // The reading pane, not the popover: a read action answers there (RADD-772).
              <ReadingPane>
                <PageView
                  key={page.data.id}
                  page={page.data}
                  spaceSlug={space.slug}
                  canWrite={canWrite}
                  canComment={canComment}
                  canManage={canManage}
                />
              </ReadingPane>
            )
          ) : browsingArchive && canBrowseArchive ? (
            archive.isPending ? (
              <Loading label="Loading archived pages…" />
            ) : archive.isError ? (
              <div className="p-6">
                <QueryError label="archived pages" error={archive.error} />
              </div>
            ) : (
              <ArchivedPagesPanel spaceId={space.id} spaceSlug={space.slug} rows={archive.data ?? []} />
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
