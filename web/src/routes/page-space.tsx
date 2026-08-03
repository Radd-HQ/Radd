import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
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
import { AiResultsPanel } from "../components/items/AiResultsPanel";
import { AiResultsContext, type AiResultRequest } from "../components/items/ai-results";

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

  // The AI results pane, shared with the issue route (RADD-772). runId bumps per
  // request so re-running the same summarize re-fires the stream.
  //
  // ABOVE the loading/error early returns, and it has to be: this component
  // returns before them, so declaring these below would change the hook count
  // between the pending render and the loaded one — the "rendered more hooks
  // than during the previous render" crash, which `tsc` has no opinion about.
  const [aiResults, setAiResults] = useState<{ request: AiResultRequest; runId: number } | null>(
    null,
  );
  const openAiResults = useCallback((request: AiResultRequest) => {
    setAiResults((current) => ({ request, runId: (current?.runId ?? 0) + 1 }));
  }, []);

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
  // A SEPARATE atom (RADD-770). The server gates a page comment on `page.read`
  // + `comment.write`, and says why: "the point of a page discussion is that
  // people who cannot edit the page can still argue about it".
  //
  // The composer used to be handed `canWrite` — and `page.write` is in
  // MEMBER_GLOBAL_SCOPE, held by every active user unconditionally. So that
  // check was not mis-scoped, it was a CONSTANT: the composer rendered for
  // everyone and refused everyone who lacked `comment.write`, which no builtin
  // role grants at global scope. A gate whose input is always true is worse than
  // no gate, because it reads as handled.
  const canComment = perms.global(Permission.commentWrite);
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

        {/* `@container/page` so the AI pane's `@4xl:` variants have something to
            query — without a container ancestor those rules never match, and the
            panel would silently stay stacked at every width (same wrapper the
            issue route carries). */}
        <div className="@container/page min-w-0 flex-1 overflow-y-auto">
          {pageSlug ? (
            page.isPending ? (
              <Spinner label="Loading page…" />
            ) : page.isError ? (
              <div className="p-6">
                <QueryError label="page" error={page.error} />
              </div>
            ) : (
              // The panel, not the popover (RADD-772). `AiReadMenu` already
              // prefers a results pane wherever one is offered — providing the
              // context IS the switch — and only the issue route ever offered
              // one, so the surface with the longest document got the smallest
              // box. Beside the page at @4xl, stacked above it below that.
              <AiResultsContext.Provider value={openAiResults}>
                <div className="flex flex-col items-start gap-3 @4xl:flex-row @4xl:justify-center">
                  {aiResults && (
                    <AiResultsPanel
                      request={aiResults.request}
                      runId={aiResults.runId}
                      onClose={() => setAiResults(null)}
                      className="order-first m-6 mb-0 w-[calc(100%-3rem)] @4xl:sticky @4xl:top-0 @4xl:order-2 @4xl:ml-0 @4xl:max-h-[calc(100vh-8rem)] @4xl:w-96 @4xl:shrink-0"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <PageView
                      key={page.data.id}
                      page={page.data}
                      spaceSlug={space.slug}
                      canWrite={canWrite}
                      canComment={canComment}
                      canManage={canManage}
                    />
                  </div>
                </div>
              </AiResultsContext.Provider>
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
