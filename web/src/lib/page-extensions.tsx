import { createContext, useContext, type ReactNode } from "react";

/**
 * Page extensions (RADD-709) — live blocks embedded in a page's markdown.
 *
 * The wire format is a fenced code block whose language is `radd:<name>`, with
 * an optional JSON object as its content:
 *
 *     ```radd:toc
 *     {"subpages": true, "depth": 3}
 *     ```
 *
 * A fence, deliberately, rather than a bespoke syntax: the body is markdown in
 * the database and is read by FTS, the embedder, the public surface, the API and
 * any export. A fence is still markdown to every one of those — a custom node
 * would have to be taught to each. It also degrades honestly: paste the page
 * anywhere else and you get a labelled code block, not garbage.
 *
 * Rendering is client-side and dispatched BY NAME through this registry, so an
 * extension a plugin contributes needs no change here (the kernel-registry
 * pattern of RADD-640). A name nobody registered renders as a labelled card
 * rather than raw JSON, because a page written against a plugin that was later
 * disabled should say so.
 */

/** What an extension is handed at render time: where it lives. */
export interface PageExtensionContext {
  /** The page the block sits on — null in previews and in non-page surfaces
   *  (comments, issue descriptions), where page-relative extensions degrade. */
  pageId: string | null;
  spaceId: string | null;
  spaceSlug: string | null;
}

export const PageExtensionCtx = createContext<PageExtensionContext>({
  pageId: null,
  spaceId: null,
  spaceSlug: null,
});

export const usePageExtensionContext = () => useContext(PageExtensionCtx);

export interface PageExtension {
  name: string;
  label: string;
  /** One line for the insert menu. */
  description: string;
  render: (params: Record<string, unknown>) => ReactNode;
}

const registry = new Map<string, PageExtension>();

export function registerPageExtension(extension: PageExtension): void {
  registry.set(extension.name, extension);
}

export const pageExtensions = (): PageExtension[] => [...registry.values()];
export const lookupPageExtension = (name: string) => registry.get(name);

/** `language-radd:toc` → `toc`; anything else → null. */
export function extensionNameOf(className: string | undefined): string | null {
  const match = /(?:^|\s)language-radd:([a-z][a-z0-9-]*)/.exec(className ?? "");
  return match ? match[1] : null;
}

/**
 * Parse a block's body into params. An empty body means "no params" — the
 * common case, and it must not read as an error. A malformed body is reported
 * as a parse failure rather than silently treated as empty, because a typo in
 * `{"subpages": true` should tell you where it is.
 */
export function parseExtensionParams(
  body: string,
): { ok: true; params: Record<string, unknown> } | { ok: false; error: string } {
  const text = body.trim();
  if (!text) return { ok: true, params: {} };
  try {
    const parsed = JSON.parse(text);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "parameters must be a JSON object" };
    }
    return { ok: true, params: parsed as Record<string, unknown> };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "invalid JSON" };
  }
}

/** The frame every extension renders inside — and the two failure states. */
export function ExtensionCard({
  label,
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <div className="my-2 rounded-lg border border-subtle bg-surface">
      {label && (
        <div className="border-b border-subtle px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
          {label}
        </div>
      )}
      <div className="px-3 py-2">{children}</div>
    </div>
  );
}

export function UnknownExtension({ name }: { name: string }) {
  return (
    <ExtensionCard label="Unknown extension">
      <p className="text-[13px] text-fg-secondary">
        Nothing is registered for <code className="font-mono text-fg">radd:{name}</code>. The
        plugin that provides it may be disabled.
      </p>
    </ExtensionCard>
  );
}

export function ExtensionError({ name, error }: { name: string; error: string }) {
  return (
    <ExtensionCard label={`radd:${name}`}>
      <p className="text-[13px] text-red-400">Could not read this block's parameters: {error}</p>
    </ExtensionCard>
  );
}
