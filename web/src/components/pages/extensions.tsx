import { useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Info,
  Link2,
  ListTree,
  Tags,
  OctagonAlert,
} from "lucide-react";
import { comparePagesNaturally } from "./PageTree";
import {
  ExtensionCard,
  registerPageExtension,
  usePageExtensionContext,
  type PageExtension,
} from "../../lib/page-extensions";
import { pageBacklinksQuery, pagesByLabelQuery, pagesQuery } from "../../lib/queries";
import { headingAnchorId, headingsOf } from "../../lib/markdown-outline";
import type { PageSummary } from "../../lib/types";
import { Markdown, MarkdownSourceCtx } from "../../lib/markdown";
import { IncludedPage } from "./IncludedPage";
import { NewFromTemplate } from "./NewFromTemplate";
import { IMPORT_EXTENSIONS } from "./ImportExtensions";
import { pageLink } from "../../lib/page-links";

/**
 * The first-party page extensions (RADD-710 / RADD-715).
 *
 * Each is a registry entry, not a special case in the renderer — which is the
 * point of RADD-709: a plugin's extension and a built-in one are the same kind
 * of thing.
 */

// --- radd:toc --------------------------------------------------------------

function TableOfContents({ params }: { params: Record<string, unknown> }) {
  const ctx = usePageExtensionContext();
  const depth = clampDepth(params.depth);
  const withSubpages = params.subpages === true;
  const source = useContext(MarkdownSourceCtx);
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
          <ul className="flex flex-col gap-0.5">
            {subpages.map(({ page, level }) => (
              <li key={page.id} style={{ paddingLeft: `${level * 12}px` }}>
                <Link
                  {...pageLink(ctx.spaceSlug ?? "", page.path)}
                  className="flex items-center gap-1 text-[13px] text-accent-text hover:underline"
                >
                  <ChevronRight size={11} aria-hidden className="shrink-0 text-fg-faint" />
                  {page.title}
                </Link>
              </li>
            ))}
          </ul>
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

/** The page's descendants, flattened with their relative level. */
function descendants(
  rows: PageSummary[],
  rootId: string | null,
  maxDepth: number,
): { page: PageSummary; level: number }[] {
  if (!rootId) return [];
  const byParent = new Map<string, PageSummary[]>();
  for (const row of rows) {
    const key = row.parent_id ?? "";
    byParent.set(key, [...(byParent.get(key) ?? []), row]);
  }
  // RADD-859: siblings render in natural order everywhere they list.
  for (const siblings of byParent.values()) siblings.sort(comparePagesNaturally);
  const out: { page: PageSummary; level: number }[] = [];
  const walk = (parentId: string, level: number) => {
    if (level >= maxDepth) return;
    for (const page of byParent.get(parentId) ?? []) {
      out.push({ page, level });
      walk(page.id, level + 1);
    }
  };
  walk(rootId, 0);
  return out;
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
        <ul className="flex flex-col gap-0.5">
          {list.map(({ page, level }) => (
            <li key={page.id} style={{ paddingLeft: `${level * 12}px` }}>
              <Link
                {...pageLink(ctx.spaceSlug ?? "", page.path)}
                className="flex items-center gap-1 text-[13px] text-accent-text hover:underline"
              >
                <ListTree size={11} aria-hidden className="shrink-0 text-fg-faint" />
                {page.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </ExtensionCard>
  );
}

// --- radd:backlinks --------------------------------------------------------

/** Every page that links here (RADD-713). Reads the index maintained on save,
 *  so this is one indexed lookup rather than a scan of every body. */
export function Backlinks() {
  const ctx = usePageExtensionContext();
  const { data, isLoading } = useQuery({
    ...pageBacklinksQuery(ctx.pageId ?? ""),
    enabled: Boolean(ctx.pageId),
  });
  return (
    <ExtensionCard label="Linked from">
      {isLoading ? (
        <p className="text-[13px] text-fg-faint">Loading…</p>
      ) : !data?.length ? (
        <p className="text-[13px] text-fg-faint">Nothing links to this page yet.</p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {data.map((page) => (
            <li key={page.id}>
              <Link
                {...pageLink(page.space_slug, page.path)}
                className="flex items-center gap-1 text-[13px] text-accent-text hover:underline"
              >
                <Link2 size={11} aria-hidden className="shrink-0 text-fg-faint" />
                {page.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </ExtensionCard>
  );
}

// --- radd:label-list -------------------------------------------------------

/**
 * Every page carrying a label (RADD-718) — Confluence's "content by label".
 *
 * This is how an index page maintains itself: the landing page declares the
 * label, and any page tagged with it appears without anyone editing a list.
 */
function LabelList({ params }: { params: Record<string, unknown> }) {
  const label = typeof params.label === "string" ? params.label.trim() : "";
  const space = typeof params.space === "string" ? params.space.trim() : "";
  const { data, isLoading } = useQuery({
    ...pagesByLabelQuery(label, space),
    enabled: Boolean(label),
  });

  if (!label) {
    return (
      <ExtensionCard label="Pages by label">
        <p className="text-[13px] text-fg-secondary">
          Set <code className="font-mono">label</code> to the label to list.
        </p>
      </ExtensionCard>
    );
  }
  return (
    <ExtensionCard label={`Pages labelled ${label}`}>
      {isLoading ? (
        <p className="text-[13px] text-fg-faint">Loading…</p>
      ) : !data?.length ? (
        <p className="text-[13px] text-fg-faint">
          No pages carry <span className="font-medium">{label}</span>
          {space ? ` in ${space}` : ""} yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {data.map((page) => (
            <li key={page.id}>
              <Link
                {...pageLink(page.space_slug, page.path)}
                className="flex items-center gap-1 text-[13px] text-accent-text hover:underline"
              >
                <Tags size={11} aria-hidden className="shrink-0 text-fg-faint" />
                {page.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </ExtensionCard>
  );
}

// --- radd:callout ----------------------------------------------------------

/**
 * The four kinds, on their own computed token scale (see `index.css`).
 *
 * Not `--chart-*`: those encode WORKFLOW STATE, and borrowing "in progress"
 * green to mean "success" would have a board legend and a page callout each
 * claiming the same colour means something different.
 *
 * Not raw palette utilities either. The first version of this used
 * `text-sky-300` on `bg-sky-500/10` — shades picked for dark, illegible on a
 * light tint. Every ink here clears 4.5:1 against its OWN fill in both themes.
 */
const CALLOUTS = {
  info: {
    icon: Info,
    cls: "border-callout-info-border bg-callout-info-fill",
    ink: "text-callout-info-ink",
  },
  success: {
    icon: CheckCircle2,
    cls: "border-callout-success-border bg-callout-success-fill",
    ink: "text-callout-success-ink",
  },
  warning: {
    icon: AlertTriangle,
    cls: "border-callout-warning-border bg-callout-warning-fill",
    ink: "text-callout-warning-ink",
  },
  danger: {
    icon: OctagonAlert,
    cls: "border-callout-danger-border bg-callout-danger-fill",
    ink: "text-callout-danger-ink",
  },
} as const;

function Callout({ params }: { params: Record<string, unknown> }) {
  const kind = (String(params.kind ?? "info") as keyof typeof CALLOUTS) in CALLOUTS
    ? (String(params.kind ?? "info") as keyof typeof CALLOUTS)
    : "info";
  const meta = CALLOUTS[kind];
  const Icon = meta.icon;
  const title = typeof params.title === "string" ? params.title : "";
  const text = typeof params.text === "string" ? params.text : "";
  return (
    <div
      data-callout-kind={kind}
      className={`my-2 flex gap-2 rounded-lg border px-3 py-2 ${meta.cls}`}
    >
      <Icon size={15} aria-hidden className={`mt-0.5 shrink-0 ${meta.ink}`} />
      <div className="min-w-0 flex-1">
        {title && (
          <p data-callout-title className={`text-[13px] font-semibold ${meta.ink}`}>
            {title}
          </p>
        )}
        {text && <Markdown text={text} />}
      </div>
    </div>
  );
}

// --- registration ----------------------------------------------------------

const EXTENSIONS: PageExtension[] = [
  {
    name: "toc",
    label: "Table of contents",
    description: "This page's headings, optionally with the pages beneath it.",
    render: (params) => <TableOfContents params={params} />,
  },
  {
    name: "children",
    label: "Child pages",
    description: "A list of the pages directly beneath this one.",
    render: (params) => <ChildPages params={params} />,
  },
  {
    name: "callout",
    label: "Callout",
    description: "A tinted note: info, success, warning or danger.",
    render: (params) => <Callout params={params} />,
  },
  {
    name: "backlinks",
    label: "Backlinks",
    description: "Every page that links to this one.",
    render: () => <Backlinks />,
  },
  {
    name: "include",
    label: "Include a page",
    description: "Render another page's body inline, live.",
    render: (params) => <IncludedPage params={params} />,
  },
  {
    name: "label-list",
    label: "Pages by label",
    description: "Every page carrying a label — an index that maintains itself.",
    render: (params) => <LabelList params={params} />,
  },
  {
    name: "new-from-template",
    label: "New page from template",
    description: "A button that creates a child page from a template.",
    render: (params) => <NewFromTemplate params={params} />,
  },
  // Spec 117. Split into their own module only because this file was at its size
  // limit; registration stays here, in the one loop below.
  ...IMPORT_EXTENSIONS,
];

for (const extension of EXTENSIONS) registerPageExtension(extension);

export { headingAnchorId };
