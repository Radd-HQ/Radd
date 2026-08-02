import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronRight, LogIn } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import {
  ApiPath,
  RoutePath,
  apiPublicPagesPagePath,
  apiPublicPagesTreePath,
} from "../lib/constants";
import type { PublicPagesPage, PublicPageNode, PublicPageSpace } from "../lib/types";
import { Markdown } from "../lib/markdown";
import { EmptyState } from "../components/EmptyState";
import { PageTree } from "../components/pages/PageTree";
import { RaddTile } from "../components/RaddMark";
import { Spinner } from "../components/Spinner";

/**
 * PUBLIC pages (spec 74) — routes `/kb`, `/kb/$spaceId`,
 * `/kb/$spaceId/$pageId`, root-level and OUTSIDE the auth gate (like
 * /public/forms/$token): anyone can read spaces an admin marked public.
 * Read-only siblings of the authed pages pages: the same PageTree + the safe
 * markdown renderer, driven by queries local to this file (the public
 * endpoints are the credential — a non-public space simply 404s).
 */

/** The minimal public chrome: Radd mark + a "Sign in" link (spec 74). */
function PublicPagesHeader({ children }: { children?: React.ReactNode }) {
  return (
    <header className="flex items-center gap-2.5 border-b border-subtle px-5 py-3">
      <Link to={RoutePath.publicPages} className="flex items-center gap-2.5">
        <RaddTile className="size-7 rounded-lg" />
        <span className="text-sm font-semibold text-heading">Radd</span>
        <span className="text-xs text-fg-muted">Pages</span>
      </Link>
      {children}
      <Link
        to={RoutePath.login}
        className="ml-auto flex items-center gap-1.5 rounded-md border border-strong px-2 py-1 text-xs text-fg hover:bg-elevated"
      >
        <LogIn size={12} aria-hidden />
        Sign in
      </Link>
    </header>
  );
}

/** `/kb` — the public space cards. */
export function PublicPagesIndexPage() {
  const spaces = useQuery({
    queryKey: ["public-kb", "spaces"],
    queryFn: () => api.get<PublicPageSpace[]>(ApiPath.publicKbSpaces),
    retry: false,
  });

  return (
    <main className="flex min-h-screen flex-col bg-base">
      <PublicPagesHeader />
      <div className="flex-1 overflow-y-auto p-6">
        {spaces.isPending ? (
          <Spinner label="Loading pages…" />
        ) : spaces.isError ? (
          <p className="text-sm text-fg-secondary">
            The pages isn't available: {errorMessage(spaces.error)}
          </p>
        ) : spaces.data.length === 0 ? (
          <EmptyState icon={BookOpen} message="Nothing has been published yet." />
        ) : (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {spaces.data.map((space) => (
              <li key={space.id}>
                <Link
                  to={RoutePath.publicPageSpace}
                  params={{ spaceId: space.id }}
                  className="flex h-full flex-col gap-1 rounded-lg border border-subtle bg-surface/50 p-4 hover:border-strong hover:bg-surface"
                >
                  <span className="flex items-center gap-2">
                    <BookOpen size={14} className="shrink-0 text-fg-muted" aria-hidden />
                    <span className="text-sm font-medium text-heading">{space.name}</span>
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
      </div>
    </main>
  );
}

/** `/kb/$spaceId` (+ `/kb/$spaceId/$pageId`) — tree rail + rendered page; with
 * no page in the URL the first root page is auto-selected. */
export function PublicPageSpacePage() {
  const { spaceId = "", pageId } = useParams({ strict: false });
  const spaces = useQuery({
    queryKey: ["public-kb", "spaces"],
    queryFn: () => api.get<PublicPageSpace[]>(ApiPath.publicKbSpaces),
    retry: false,
  });
  const tree = useQuery({
    queryKey: ["public-kb", "tree", spaceId],
    queryFn: () => api.get<PublicPageNode[]>(apiPublicPagesTreePath(spaceId)),
    retry: false,
    enabled: spaceId !== "",
  });

  const rows = tree.data ?? [];
  // First page auto-selected: the top root row (rows arrive position-sorted).
  const activePageId = pageId ?? rows.find((row) => row.parent_id === null)?.id;
  const page = useQuery({
    queryKey: ["public-kb", "page", activePageId ?? ""],
    queryFn: () => api.get<PublicPagesPage>(apiPublicPagesPagePath(activePageId ?? "")),
    retry: false,
    enabled: Boolean(activePageId),
  });

  const space = spaces.data?.find((entry) => entry.id === spaceId);

  return (
    <main className="flex h-screen flex-col bg-base">
      <PublicPagesHeader>
        {space && (
          <span className="flex min-w-0 items-center gap-1.5 text-sm">
            <ChevronRight size={13} className="shrink-0 text-fg-faint" aria-hidden />
            <Link
              to={RoutePath.publicPageSpace}
              params={{ spaceId }}
              className="truncate font-medium text-heading hover:underline"
            >
              {space.name}
            </Link>
            {page.data?.breadcrumb.map((crumb) => (
              <span key={crumb.id} className="flex min-w-0 items-center gap-1.5">
                <ChevronRight size={13} className="shrink-0 text-fg-faint" aria-hidden />
                <Link
                  to={RoutePath.publicPage}
                  params={{ spaceId, pageId: crumb.id }}
                  className="truncate text-fg-secondary hover:text-fg"
                >
                  {crumb.title}
                </Link>
              </span>
            ))}
          </span>
        )}
      </PublicPagesHeader>

      {tree.isPending ? (
        <Spinner label="Loading pages…" />
      ) : tree.isError ? (
        <p className="p-6 text-sm text-fg-secondary">
          This pages isn't available: {errorMessage(tree.error)}
        </p>
      ) : (
        <div className="flex min-h-0 flex-1">
          <nav
            aria-label="Page tree"
            className="w-64 shrink-0 overflow-y-auto border-r border-subtle p-2"
          >
            <PageTree
              spaceId={spaceId}
              rows={rows}
              selectedId={activePageId}
              canWrite={false}
              pageRoute={RoutePath.publicPage}
            />
          </nav>

          <div className="min-w-0 flex-1 overflow-y-auto">
            {activePageId ? (
              page.isPending ? (
                <Spinner label="Loading page…" />
              ) : page.isError ? (
                <p className="p-6 text-sm text-fg-secondary">
                  This page isn't available: {errorMessage(page.error)}
                </p>
              ) : (
                <article className="mx-auto max-w-3xl px-6 py-5">
                  <h1 className="text-xl font-semibold text-heading">{page.data.title}</h1>
                  <div className="mt-3">
                    {page.data.body ? (
                      <Markdown text={page.data.body} />
                    ) : (
                      <p className="text-[13px] text-fg-faint">This page is empty.</p>
                    )}
                  </div>
                </article>
              )
            ) : (
              <div className="p-6">
                <EmptyState icon={BookOpen} message="This space has no pages yet." />
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
