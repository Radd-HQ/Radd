import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Archive, BookOpen, ChevronRight } from "lucide-react";
import { AiResultsPane, Button, EmptyState, ErrorText, Modal, QueryError } from "@radd/plugin-sdk";
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

/**
 * `/pages/$spaceSlug` (+ `/pages/$spaceSlug/<path…>`) — the two-pane pages
 * view (spec 43): the collapsible tree beside the selected page.
 *
 * The page segment is a PATH through the tree (RADD-1233), carried by the
 * splat. The space may be an id; a single page segment may be a number or an
 * id; a stale path resolves through the page's old addresses (RADD-702's
 * promise, kept by the server). Whatever address you arrived by, the effect
 * below rewrites the bar to the canonical one the answer carries. It REPLACES
 * the history entry — arriving by an old link shouldn't cost the visitor a
 * Back press to escape.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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
  // RADD-1240 (radd-hq/radd#12): an agent handed a page's id assembled
  // `/pages/<uuid>` itself — a SPACE address that does not exist, answered
  // with "Page space not found." and nowhere to go. When the segment is a
  // uuid no space owns, ask whether it names a page, and land on the page.
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

  // RADD-810: all three resolve against THIS space — the server checks them at
  // space scope (RADD-791; page comments via comments_binding), so a member
  // granted page.write in one space finally sees its editors. The old global
  // questions were false for every space-scoped grant holder.
  const canWrite = perms.space(space, PagePermission.write);
  const canManage = perms.space(space, PagePermission.manage);
  // A SEPARATE atom (RADD-770). The server gates a page comment on `page.read`
  // + `comment.write`, resolved in the space (comments_binding.py), and says
  // why: "the point of a page discussion is that people who cannot edit the
  // page can still argue about it".
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

        {/* `@container/page` so the AI pane's `@4xl:` variants have something to
            query — without a container ancestor those rules never match, and the
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
              // The panel, not the popover (RADD-772). `AiReadMenu` already
              // prefers a results pane wherever one is offered — providing it
              // IS the switch — and only the issue route ever offered one, so
              // the surface with the longest document got the smallest box.
              <AiResultsPane>
                <PageView
                  key={page.data.id}
                  page={page.data}
                  spaceSlug={space.slug}
                  canWrite={canWrite}
                  canComment={canComment}
                  canManage={canManage}
                />
              </AiResultsPane>
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
