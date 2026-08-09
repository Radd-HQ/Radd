import { useState } from "react";
import { useQuery, queryOptions } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, OctagonAlert, Puzzle } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, entityMeta } from "../../lib/cache";
import { ApiPath, ITEMS_PAGE_LIMIT, RoutePath } from "../../lib/constants";
import { ExtensionCard, type PageExtension } from "../../lib/page-extensions";
import { Markdown } from "../../lib/markdown";
import type { Item } from "../../lib/types";

/**
 * The three extensions the Confluence importer needs (spec 117, RADD-1019).
 *
 * They live here rather than in `extensions.tsx` only because that file was
 * already at its size limit; registration still happens in one place, by
 * spreading `IMPORT_EXTENSIONS` into the single `EXTENSIONS` array.
 *
 * Each ships its renderer in the same commit as its kernel declaration:
 * `tests/test_page_extensions.py` compares the TypeScript list to the kernel's in
 * BOTH directions, so a name declared without a renderer fails the build rather
 * than landing as an "unknown extension" card on every imported page.
 */

// --- radd:unsupported-macro ------------------------------------------------

/**
 * The honest fallback for a Confluence macro Radd cannot render.
 *
 * It exists so the importer never has to choose between guessing and deleting.
 * The macro's name and parameters are preserved verbatim, which means building
 * the real renderer later upgrades every instance in place — the raw body is
 * still in the snapshot cache, so it is a re-convert, not a re-download.
 */
function UnsupportedMacro({ params }: { params: Record<string, unknown> }) {
  const macro = typeof params.macro === "string" ? params.macro : "unknown";
  const values =
    params.params && typeof params.params === "object"
      ? (params.params as Record<string, unknown>)
      : {};
  const body = typeof params.body === "string" ? params.body : "";
  const entries = Object.entries(values).filter(([, v]) => String(v ?? "").trim());

  return (
    <ExtensionCard label={`Unsupported macro · ${macro}`}>
      <div className="flex items-start gap-2">
        <Puzzle className="mt-0.5 size-4 shrink-0 text-fg-faint" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-fg-secondary">
            This page used the Confluence <code className="text-fg">{macro}</code> macro,
            which Radd does not render yet. Its content is kept below so nothing is lost.
          </p>
          {entries.length > 0 && (
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
              {entries.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="text-fg-faint">{key}</dt>
                  <dd className="truncate text-fg-secondary">{String(value)}</dd>
                </div>
              ))}
            </dl>
          )}
          {body && (
            <div className="mt-2 border-t border-subtle pt-2">
              <Markdown text={body} />
            </div>
          )}
        </div>
      </div>
    </ExtensionCard>
  );
}

// --- radd:expand -----------------------------------------------------------

/** A collapsible section — Confluence's `expand`, and useful on its own. */
function Expand({ params }: { params: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const title = typeof params.title === "string" && params.title.trim() ? params.title : "Details";
  const text = typeof params.text === "string" ? params.text : "";

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-subtle bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[13px] font-medium text-heading hover:bg-elevated"
      >
        <ChevronRight
          className={`size-4 shrink-0 text-fg-muted transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden
        />
        {title}
      </button>
      {open && (
        <div className="border-t border-subtle px-3 py-2">
          <Markdown text={text} />
        </div>
      )}
    </div>
  );
}

// --- radd:items ------------------------------------------------------------

/** An SLQ query rendered as a table — what a Confluence `jiraissues` becomes. */
const slqItemsQuery = (q: string) =>
  queryOptions({
    queryKey: ["page-extension-items", q],
    meta: entityMeta(Entity.item),
    enabled: Boolean(q),
    queryFn: () =>
      api.get<Item[]>(ApiPath.items, {
        query: { q, limit: String(Math.min(50, ITEMS_PAGE_LIMIT)) },
      }),
  });

function ItemsTable({ params }: { params: Record<string, unknown> }) {
  const query = typeof params.query === "string" ? params.query.trim() : "";
  const sourceJql = typeof params.source_jql === "string" ? params.source_jql : "";
  const unsupported = params.unsupported === true || !query;
  const result = useQuery(slqItemsQuery(unsupported ? "" : query));

  // An untranslatable JQL is shown, not guessed at. A silently mistranslated
  // query that returns plausible rows is worse than one that asks for a human.
  if (unsupported) {
    return (
      <ExtensionCard label="Issue query">
        <div className="flex items-start gap-2">
          <OctagonAlert className="mt-0.5 size-4 shrink-0 text-fg-faint" aria-hidden />
          <div className="min-w-0">
            <p className="text-[13px] text-fg-secondary">
              This came from a Jira query that could not be translated to SLQ. The original
              is kept so it can be rewritten by hand.
            </p>
            {sourceJql && (
              <pre className="mt-2 overflow-x-auto rounded bg-elevated px-2 py-1 text-[12px] text-fg-secondary">
                {sourceJql}
              </pre>
            )}
          </div>
        </div>
      </ExtensionCard>
    );
  }

  if (result.isLoading) {
    return (
      <ExtensionCard label="Issues">
        <p className="text-[13px] text-fg-faint">Loading…</p>
      </ExtensionCard>
    );
  }
  if (result.isError) {
    return (
      <ExtensionCard label="Issues">
        <p className="text-[13px] text-fg-faint">
          That query could not be run: <code className="text-fg-secondary">{query}</code>
        </p>
      </ExtensionCard>
    );
  }

  const items = result.data ?? [];
  if (!items.length) {
    return (
      <ExtensionCard label="Issues">
        <p className="text-[13px] text-fg-faint">No issues match this query.</p>
      </ExtensionCard>
    );
  }

  return (
    <ExtensionCard label={`Issues · ${items.length}`}>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-subtle last:border-0">
                <td className="py-1 pr-3 align-top">
                  <Link
                    to={RoutePath.issue}
                    params={{ itemKey: item.key }}
                    className="font-mono text-[12px] text-accent-text hover:underline"
                  >
                    {item.key}
                  </Link>
                </td>
                <td className="py-1 pr-3 align-top text-fg">{item.title}</td>
                <td className="py-1 align-top text-[12px] text-fg-muted">
                  {item.state?.name ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ExtensionCard>
  );
}

export const IMPORT_EXTENSIONS: PageExtension[] = [
  {
    name: "unsupported-macro",
    label: "Unsupported macro",
    description: "An imported macro Radd cannot render yet, kept verbatim.",
    render: (params) => <UnsupportedMacro params={params} />,
  },
  {
    name: "expand",
    label: "Expand",
    description: "A collapsible section.",
    render: (params) => <Expand params={params} />,
  },
  {
    name: "items",
    label: "Issue query",
    description: "Issues matching an SLQ query, as a table.",
    render: (params) => <ItemsTable params={params} />,
  },
];
