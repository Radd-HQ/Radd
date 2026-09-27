import { useState } from "react";
import { useQuery, queryOptions } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, OctagonAlert, Play, Puzzle } from "lucide-react";
import { api, ExtensionCard, Markdown, type Item, Entity } from "@radd/plugin-sdk";
import { ISSUE_ROUTE } from "../endpoints";
import type { ExtensionRenderers } from "../extension-registry";

/** A `radd:items` table shows at most this many issues. */
const ITEMS_TABLE_LIMIT = 50;

/** The importers' blocks (spec 117). Declared in `extension-registry.tsx`; `test_page_extensions.py`
 *  checks every declaration has a renderer here or in `extensions.tsx`. */

// --- radd:unsupported-macro ------------------------------------------------

/** A macro Radd cannot render: name, params and body kept verbatim, so a real renderer later upgrades it in place. */
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
    meta: { entities: [Entity.item] },
    enabled: Boolean(q),
    queryFn: ({ signal }) =>
      api.get<Item[]>("/items", {
        signal,
        query: { q, limit: String(ITEMS_TABLE_LIMIT) },
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
                    to={ISSUE_ROUTE}
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

// --- radd:media ------------------------------------------------------------

/** A playable attachment. Native players on purpose: the browser handles range requests and codecs. */
function Media({ params }: { params: Record<string, unknown> }) {
  const src = typeof params.src === "string" ? params.src : "";
  const kind = params.kind === "audio" ? "audio" : "video";
  const title = typeof params.title === "string" ? params.title : "";
  const poster = typeof params.poster === "string" ? params.poster : undefined;

  if (!src) {
    return (
      <ExtensionCard label="Media">
        <p className="text-[13px] text-fg-faint">This block names no file to play.</p>
      </ExtensionCard>
    );
  }

  return (
    <figure className="my-3">
      {kind === "audio" ? (
        <audio controls preload="metadata" src={src} className="w-full">
          <a href={src}>Download the audio</a>
        </audio>
      ) : (
        <video
          controls
          preload="metadata"
          src={src}
          poster={poster}
          className="max-h-[70vh] w-full rounded-lg border border-subtle bg-black"
        >
          <a href={src}>Download the video</a>
        </video>
      )}
      {title && (
        <figcaption className="mt-1 flex items-center gap-1.5 text-[12px] text-fg-muted">
          <Play className="size-3.5" aria-hidden />
          <a href={src} className="truncate hover:underline" download>
            {title}
          </a>
        </figcaption>
      )}
    </figure>
  );
}

export const IMPORT_RENDERERS: ExtensionRenderers = {
  media: (params) => <Media params={params} />,
  "unsupported-macro": (params) => <UnsupportedMacro params={params} />,
  expand: (params) => <Expand params={params} />,
  items: (params) => <ItemsTable params={params} />,
};
