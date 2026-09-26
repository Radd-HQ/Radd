import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2, Info, Link2, OctagonAlert, Tags, type LucideIcon } from "lucide-react";
import { ExtensionCard, Markdown, usePageExtensionContext } from "@radd/plugin-sdk";
import { pageLink } from "../links";
import { pageBacklinksQuery, pagesByLabelQuery } from "../queries";

/** The first-party blocks that list or frame: backlinks, pages by label, and the callout
 *  (RADD-713/718/715). Their renderers are registered with the rest in `extensions.tsx`. */

/** The link list the outline and index blocks share; `level` indents a row. */
export function PageLinkList({ rows, icon: Icon }: {
  rows: { id: string; title: string; path: string; spaceSlug: string; level?: number }[];
  icon: LucideIcon;
}) {
  return (
    <ul className="flex flex-col gap-0.5">
      {rows.map((row) => (
        <li key={row.id} style={row.level === undefined ? undefined : { paddingLeft: `${row.level * 12}px` }}>
          <Link
            {...pageLink(row.spaceSlug, row.path)}
            className="flex items-center gap-1 text-[13px] text-accent-text hover:underline"
          >
            <Icon size={11} aria-hidden className="shrink-0 text-fg-faint" />
            {row.title}
          </Link>
        </li>
      ))}
    </ul>
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
        <PageLinkList icon={Link2} rows={data.map((page) => ({ ...page, spaceSlug: page.space_slug }))} />
      )}
    </ExtensionCard>
  );
}

// --- radd:label-list -------------------------------------------------------

/** Every page carrying a label (RADD-718) — an index page that maintains itself. */
export function LabelList({ params }: { params: Record<string, unknown> }) {
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
        <PageLinkList icon={Tags} rows={data.map((page) => ({ ...page, spaceSlug: page.space_slug }))} />
      )}
    </ExtensionCard>
  );
}

// --- radd:callout ----------------------------------------------------------

/** The four kinds on the `--callout-*` scale — not `--chart-*`, which encodes WORKFLOW STATE; every
 *  ink clears 4.5:1 on its own fill in both themes. */
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

export function Callout({ params }: { params: Record<string, unknown> }) {
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
