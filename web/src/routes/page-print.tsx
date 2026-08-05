import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearch } from "@tanstack/react-router";
import { pageByPathQuery, pagesQuery, usersQuery } from "../lib/queries";
import { PageBody } from "../components/pages/PageBody";
import { PageExtensionCtx } from "../lib/page-extensions";
import { headingAnchorId, headingsOf } from "../lib/markdown-outline";
import type { PageSummary } from "../lib/types";
import { formatDate } from "../lib/dates";
import "./page-print.css";

/**
 * The print view (RADD-733/734): one page, or a page and its subtree, with no
 * application chrome at all.
 *
 * Rendered by the browser's own PDF engine rather than server-side. A faithful
 * PDF has to run the same Crepe renderer the app does, which would mean headless
 * Chromium in the runtime image — about a gigabyte on an image whose reason to
 * exist is being self-hosted, for an engine every reader already has. Going
 * through markdown-to-PDF instead (WeasyPrint, reportlab) avoids the weight by
 * reimplementing the renderer, so code blocks, chips, tables and every future
 * extension would drift from what the page looks like on screen.
 *
 * A top-level route, NOT a child of the app layout: the layout is precisely
 * what must not be in the output.
 */
export function PagePrintPage() {
  const { spaceSlug, pageSlug } = useParams({ strict: false }) as {
    spaceSlug: string;
    pageSlug: string;
  };
  const search = useSearch({ strict: false }) as { subpages?: boolean };
  const withSubpages = search.subpages === true;

  const { data: page } = useQuery(pageByPathQuery(spaceSlug, pageSlug));
  const { data: users } = useQuery(usersQuery);
  const { data: rows, isSuccess: treeLoaded } = useQuery({
    ...pagesQuery(page?.space_id ?? ""),
    enabled: Boolean(page?.space_id) && withSubpages,
  });

  const subtree = useMemo(
    () => (withSubpages && page ? descendants(rows ?? [], page.id) : []),
    [withSubpages, page, rows],
  );

  // RADD-736: every body has to have RENDERED before print() — Crepe creates
  // asynchronously, so printing on mount produces blank pages. One counter for
  // the root plus each subpage.
  const expected = 1 + subtree.length;
  const [rendered, setRendered] = useState(0);
  const printed = useRef(false);

  // Force the LIGHT theme for the whole document while this route is mounted.
  // Without it the body prints in dark-theme colours — the first PDF came out
  // with near-invisible grey headings on white and solid dark code blocks,
  // because the app ships dark and Crepe carries its own dark stylesheet. The
  // theme is a class-driven variable remap, so flipping the class is enough;
  // nothing here hardcodes a colour.
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
          pageSlug={child.slug}
          onReady={bump}
        />
      ))}

      <footer className="radd-print-footer">
        {window.location.origin}/pages/{spaceSlug}/{pageSlug}
      </footer>
    </div>
  );
}

/** One subpage, starting on a fresh sheet. */
function SubPage({
  pageId,
  spaceId,
  spaceSlug,
  pageSlug,
  onReady,
}: {
  pageId: string;
  spaceId: string;
  spaceSlug: string;
  pageSlug: string;
  onReady: () => void;
}) {
  const { data } = useQuery(pageByPathQuery(spaceSlug, pageSlug));
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

/** Depth-first descendants in tree order — the same order the rail shows. */
function descendants(rows: PageSummary[], rootId: string): { page: PageSummary; level: number }[] {
  const byParent = new Map<string, PageSummary[]>();
  for (const row of rows) {
    const key = row.parent_id ?? "";
    byParent.set(key, [...(byParent.get(key) ?? []), row]);
  }
  const out: { page: PageSummary; level: number }[] = [];
  const walk = (parentId: string, level: number) => {
    for (const page of byParent.get(parentId) ?? []) {
      out.push({ page, level });
      walk(page.id, level + 1);
    }
  };
  walk(rootId, 0);
  return out;
}

export { headingsOf };
