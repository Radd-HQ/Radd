import { useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, ListTree } from "lucide-react";
import { ExtensionCard, MarkdownSourceContext, headingsOf, usePageExtensionContext } from "@radd/plugin-sdk";
import { provideExtensionRenderers, type ExtensionRenderers } from "../extension-registry";
import { pageLink } from "../links";
import { pagesQuery } from "../queries";
import { descendants } from "./page-tree";
import { IncludedPage } from "./IncludedPage";
import { NewFromTemplate } from "./NewFromTemplate";
import { IMPORT_RENDERERS } from "./ImportExtensions";
import { Backlinks, Callout, LabelList, PageLinkList } from "./ListExtensions";

// --- radd:toc --------------------------------------------------------------

function TableOfContents({ params }: { params: Record<string, unknown> }) {
  const ctx = usePageExtensionContext();
  const depth = clampDepth(params.depth);
  const withSubpages = params.subpages === true;
  const source = useContext(MarkdownSourceContext);
  const headings = headingsOf(source, depth);

  const children = useQuery({
    ...pagesQuery(ctx.spaceId ?? ""),
    enabled: withSubpages && Boolean(ctx.spaceId),
  });
  const subpages = withSubpages ? descendants(children.data ?? [], ctx.pageId, depth) : [];

  if (!headings.length && !subpages.length) {
    return (
      <ExtensionCard label="On this page">
        <p className="text-[13px] text-fg-faint">
          {withSubpages
            ? "No headings on this page, and nothing beneath it yet."
            : "No headings on this page yet."}
        </p>
      </ExtensionCard>
    );
  }

  return (
    <ExtensionCard label="On this page">
      {headings.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {headings.map((heading) => (
            <li key={heading.id} style={{ paddingLeft: `${(heading.level - 1) * 12}px` }}>
              <a
                href={`#${heading.id}`}
                className="text-[13px] text-accent-text hover:underline"
              >
                {heading.text}
              </a>
            </li>
          ))}
        </ul>
      )}
      {subpages.length > 0 && (
        <div className={headings.length ? "mt-2 border-t border-subtle pt-2" : ""}>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
            Pages below this one
          </p>
          <PageLinkList icon={ChevronRight}
            rows={subpages.map(({ page, level }) => ({ ...page, spaceSlug: ctx.spaceSlug ?? "", level }))} />
        </div>
      )}
    </ExtensionCard>
  );
}

/** Depth defaults to 3 — deep enough to be an outline, shallow enough to stay one. */
function clampDepth(raw: unknown): number {
  const value = typeof raw === "number" ? raw : Number.parseInt(String(raw ?? ""), 10);
  return Number.isFinite(value) ? Math.min(Math.max(value, 1), 6) : 3;
}

// --- radd:children ---------------------------------------------------------

function ChildPages({ params }: { params: Record<string, unknown> }) {
  const ctx = usePageExtensionContext();
  const rows = useQuery({ ...pagesQuery(ctx.spaceId ?? ""), enabled: Boolean(ctx.spaceId) });
  const depth = params.depth === undefined ? 1 : clampDepth(params.depth);
  const list = descendants(rows.data ?? [], ctx.pageId, depth);
  // RADD-858: embed transcludes every child's LIVE body via the same
  // component radd:include uses (cycle guard inherited), each under its
  // title — one unified page that updates itself as children arrive.
  if (params.mode === "embed") {
    return (
      <div className="flex flex-col gap-1">
        {list.length === 0 && (
          <ExtensionCard label="Child pages">
            <p className="text-[13px] text-fg-faint">No child pages yet.</p>
          </ExtensionCard>
        )}
        {list.map(({ page }) => (
          <section key={page.id}>
            <h2 className="mt-4 mb-1 text-lg font-semibold text-heading">
              <Link
                {...pageLink(ctx.spaceSlug ?? "", page.path)}
                className="hover:underline"
              >
                {page.title}
              </Link>
            </h2>
            <IncludedPage params={{ page: page.path }} />
          </section>
        ))}
      </div>
    );
  }
  return (
    <ExtensionCard label="Child pages">
      {list.length === 0 ? (
        <p className="text-[13px] text-fg-faint">No child pages yet.</p>
      ) : (
        <PageLinkList icon={ListTree}
          rows={list.map(({ page, level }) => ({ ...page, spaceSlug: ctx.spaceSlug ?? "", level }))} />
      )}
    </ExtensionCard>
  );
}

// --- renderers ---------------------------------------------------------------

// The registry entries (names, labels) are declared in `extension-registry.tsx`, eagerly; these
// renderers load with the first block that needs one, and with the wiki's own routes.
const RENDERERS: ExtensionRenderers = {
  toc: (params) => <TableOfContents params={params} />,
  children: (params) => <ChildPages params={params} />,
  callout: (params) => <Callout params={params} />,
  backlinks: () => <Backlinks />,
  include: (params) => <IncludedPage params={params} />,
  "label-list": (params) => <LabelList params={params} />,
  "new-from-template": (params) => <NewFromTemplate params={params} />,
};

provideExtensionRenderers({ ...RENDERERS, ...IMPORT_RENDERERS });
