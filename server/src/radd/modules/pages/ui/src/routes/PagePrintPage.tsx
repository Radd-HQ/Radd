import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearch } from "@tanstack/react-router";
import "./page-print.css";
import { formatDate, headingAnchorId, useIsAuthenticated, PageExtensionCtx } from "@radd/plugin-sdk";
import { pageByPathQuery, pageQuery, pagesQuery } from "../queries";
import { pageHref } from "../links";
import { PageBody } from "../view/PageBody";
import { usePeople } from "../view/people";
import { descendants } from "../view/page-tree";

/**
 * The print view (RADD-733): a page, or a page and its subtree, with no app chrome. The browser's
 * own PDF engine renders it, so the output is the on-screen renderer, not a reimplementation. A
 * top-level route, outside the app layout — the layout is what must not print.
 */
export function PagePrintPage() {
  const { spaceSlug, _splat: pagePath = "" } = useParams({ strict: false }) as {
    spaceSlug: string;
    _splat?: string;
  };
  const search = useSearch({ strict: false }) as { subpages?: boolean };
  const withSubpages = search.subpages === true;

  const { data: page } = useQuery(pageByPathQuery(spaceSlug, pagePath));
  const users = usePeople(useIsAuthenticated());
  const { data: rows, isSuccess: treeLoaded } = useQuery({
    ...pagesQuery(page?.space_id ?? ""),
    enabled: Boolean(page?.space_id) && withSubpages,
  });

  const subtree = useMemo(
    () => (withSubpages && page ? descendants(rows ?? [], page.id) : []),
    [withSubpages, page, rows],
  );

  // Print only after EVERY body has rendered (RADD-736); the viewers mount asynchronously.
  const expected = 1 + subtree.length;
  const [rendered, setRendered] = useState(0);
  const printed = useRef(false);

  // Force the light theme while mounted: the app ships dark, and printing it is illegible.
  useEffect(() => {
    const root = document.documentElement;
    const wasLight = root.classList.contains("light");
    root.classList.add("light");
    return () => {
      if (!wasLight) root.classList.remove("light");
    };
  }, []);

  useEffect(() => {
    if (!page || rendered < expected || printed.current) return;
    // The subtree decides how many bodies to wait for, so printing before the
    // TREE has loaded races to `expected === 1` and emits the root alone — the
    // exact failure "export with subpages" is supposed to avoid.
    if (withSubpages && !treeLoaded) return;
    printed.current = true;
    // One frame, so the final layout pass lands before the print snapshot.
    const id = requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
    return () => cancelAnimationFrame(id);
  }, [page, rendered, expected, withSubpages, treeLoaded]);

  if (!page) return null;

  const author = users?.find((user) => user.id === page.updated_by);
  const bump = () => setRendered((count) => count + 1);

  return (
    <div className="radd-print">
      <article className="radd-print-page">
        <header className="radd-print-head">
          <p className="radd-print-space">{page.space.name}</p>
          <h1>{page.title}</h1>
          <p className="radd-print-meta">
            Last edited by {author?.name ?? "someone"} on{" "}
            {formatDate(page.updated_at)}
          </p>
        </header>

        {/* A contents list only when there is a subtree — for a single page the
            body's own headings are right there. */}
        {subtree.length > 0 && (
          <nav className="radd-print-contents">
            <h2>Contents</h2>
            <ol>
              <li>{page.title}</li>
              {subtree.map(({ page: child, level }) => (
                <li key={child.id} style={{ marginLeft: `${level * 14}px` }}>
                  {child.title}
                </li>
              ))}
            </ol>
          </nav>
        )}

        <PageExtensionCtx.Provider
          value={{ pageId: page.id, spaceId: page.space_id, spaceSlug }}
        >
          <PageBody text={page.body} onReady={bump} />
        </PageExtensionCtx.Provider>
      </article>

      {subtree.map(({ page: child }) => (
        <SubPage
          key={child.id}
          pageId={child.id}
          spaceId={page.space_id}
          spaceSlug={spaceSlug}
          onReady={bump}
        />
      ))}

      <footer className="radd-print-footer">
        {window.location.origin}
        {pageHref(page.space.slug, page.path)}
      </footer>
    </div>
  );
}

/** One subpage, starting on a fresh sheet. */
function SubPage({
  pageId,
  spaceId,
  spaceSlug,
  onReady,
}: {
  pageId: string;
  spaceId: string;
  spaceSlug: string;
  onReady: () => void;
}) {
  // By id: the tree row already names the child, and an id needs no path.
  const { data } = useQuery(pageQuery(pageId));
  // The body has to arrive before it can render; report ready only once it has.
  useEffect(() => {
    if (data && !data.body) onReady();
  }, [data, onReady]);
  if (!data) return null;
  return (
    <article className="radd-print-page radd-print-break">
      <h1 id={headingAnchorId(data.title)}>{data.title}</h1>
      <PageExtensionCtx.Provider value={{ pageId, spaceId, spaceSlug }}>
        <PageBody text={data.body} onReady={onReady} />
      </PageExtensionCtx.Provider>
    </article>
  );
}
