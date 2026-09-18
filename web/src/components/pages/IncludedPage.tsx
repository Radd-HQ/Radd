import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { pageLink } from "../../lib/page-links";
import { pageByPathQuery } from "../../lib/queries";
import { ExtensionCard, usePageExtensionContext } from "../../lib/page-extensions";
import { PageBody } from "./PageBody";

/**
 * `radd:include` — render another page's body here, live (RADD-716).
 *
 * A shared fragment (a warning, a contact list, a set of links) otherwise has to
 * be copy-pasted into every page that needs it, and then drifts. Including it
 * means editing the source updates every page that includes it.
 *
 * **The cycle guard is the load-bearing part.** A page that includes itself —
 * directly, or through a chain — would recurse until the browser tab dies.
 * `IncludeChainCtx` carries the ids currently being rendered ABOVE this point;
 * a target already in the chain renders a message naming the loop instead of
 * descending into it. This is why the guard lives in React context rather than
 * in a lookup at fetch time: the cycle is a property of the render stack, and
 * A→B, B→A is only a cycle when you are already inside A.
 *
 * Permissions need no special handling: the include fetches through the normal
 * page endpoint with the reader's own session, so a page they may not read comes
 * back 403 and renders as "cannot be shown" rather than leaking a body.
 */
const IncludeChainCtx = createContext<readonly string[]>([]);

export function IncludedPage({ params }: { params: Record<string, unknown> }) {
  const ctx = usePageExtensionContext();
  const chain = useContext(IncludeChainCtx);
  const raw = typeof params.page === "string" ? params.page.trim() : "";

  // RADD-1233: `page` is a PATH in this space (`slug/slug`), or a page number;
  // `<space>:<path>` reaches into another space. The colon, not a slash — a
  // slash is a path separator now, so `a/b` has to mean "b under a, here".
  const colon = raw.indexOf(":");
  const [spaceSlug, pagePath] =
    colon > 0 ? [raw.slice(0, colon), raw.slice(colon + 1)] : [ctx.spaceSlug ?? "", raw];

  const { data, isLoading, isError, error } = useQuery({
    ...pageByPathQuery(spaceSlug, pagePath),
    enabled: Boolean(spaceSlug && pagePath),
  });

  if (!raw) {
    return (
      <ExtensionCard label="Include">
        <p className="text-[13px] text-fg-secondary">
          Set <code className="font-mono">page</code> to the path of the page to include
          (<code className="font-mono">parent/child</code>), its number, or{" "}
          <code className="font-mono">space:path</code> for a page in another space.
        </p>
      </ExtensionCard>
    );
  }

  // The whole chain above us, plus the page this block sits on.
  const above = [...chain, ctx.pageId].filter(Boolean) as string[];
  if (data && above.includes(data.id)) {
    return (
      <ExtensionCard label="Include">
        <p className="text-[13px] text-fg-secondary">
          <span className="font-semibold">{data.title}</span> already contains this include —
          rendering it here would loop forever.
        </p>
      </ExtensionCard>
    );
  }

  if (isLoading) {
    return (
      <ExtensionCard label="Include">
        <p className="text-[13px] text-fg-faint">Loading {raw}…</p>
      </ExtensionCard>
    );
  }
  if (isError || !data) {
    return (
      <ExtensionCard label="Include">
        <p className="text-[13px] text-fg-secondary">
          Could not show <code className="font-mono">{raw}</code>
          {error instanceof Error && error.message.includes("403")
            ? " — you do not have access to it."
            : " — no such page."}
        </p>
      </ExtensionCard>
    );
  }

  return (
    <div className="my-2 rounded-lg border border-dashed border-strong bg-surface">
      {/* A visible boundary, so a reader can tell included content from content
          written here — otherwise an edit to the source silently rewrites what
          looks like this page's own words. */}
      <div className="flex items-center gap-1.5 border-b border-dashed border-strong px-3 py-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
          Included from
        </span>
        <Link
          {...pageLink(data.space.slug, data.path)}
          className="flex items-center gap-1 text-[12px] text-accent-text hover:underline"
        >
          {data.title}
          <ExternalLink size={10} aria-hidden />
        </Link>
      </div>
      <div className="px-3 py-2">
        <IncludeChainCtx.Provider value={above}>
          <PageBody text={data.body} />
        </IncludeChainCtx.Provider>
      </div>
    </div>
  );
}
