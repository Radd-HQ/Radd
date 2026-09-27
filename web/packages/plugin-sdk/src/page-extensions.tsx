import { createContext, useContext, type ReactNode } from "react";

/**
 * Page extensions: live blocks written as a fenced code block whose language is `radd:<name>`,
 * with an optional JSON object as the body. A fence stays markdown to FTS, the embedder, the API
 * and any export, and degrades to a labelled code block anywhere else. Rendering is dispatched BY
 * NAME through this registry; an unregistered name renders as a labelled card (its plugin may be
 * disabled). The registry and both contexts live in the SDK because they are shared state: a
 * context reaches a consumer only through the very same object.
 */

/** The markdown source the block sits in — a `radd:toc` lists this source's
 *  headings. Every renderer provides it: the read-mode markdown, the editor
 *  (live, as you type) and a page body. */
export const MarkdownSourceContext = createContext<string>("");

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

/** A fence's info string → the extension name it names, or null. */
export function extensionNameOfInfo(info: string): string | null {
  const match = /^radd:([a-z][a-z0-9-]*)$/.exec(info.trim());
  return match ? match[1] : null;
}

export type BodySegment =
  | { kind: "markdown"; text: string }
  | { kind: "extension"; name: string; body: string };

/** Opens a fence: up to three spaces of indent, then ``` or ~~~, then the info. */
const FENCE_OPEN = /^(\s{0,3})(`{3,}|~{3,})[ \t]*(.*)$/;

/**
 * Split a page body into prose runs and extension blocks, so read mode renders each extension as
 * ordinary React (router, query client and page context intact) and each prose run through the
 * viewer; a page with no extensions stays one run. Fences are tracked, not regex-swept: a
 * ```` ```radd:toc ```` inside a ```` ```markdown ```` example is documentation and stays code.
 */
export function splitExtensionBlocks(markdown: string): BodySegment[] {
  const lines = markdown.split("\n");
  const segments: BodySegment[] = [];
  let prose: string[] = [];

  const flush = () => {
    const text = prose.join("\n");
    // Whitespace-only runs (the blank line between two adjacent extensions)
    // would otherwise each cost an editor instance rendering nothing.
    if (text.trim()) segments.push({ kind: "markdown", text });
    prose = [];
  };

  for (let index = 0; index < lines.length; index++) {
    const open = FENCE_OPEN.exec(lines[index]);
    if (!open) {
      prose.push(lines[index]);
      continue;
    }
    const [, , marker, info] = open;
    // A fence closes on the same character, at least as long, and nothing else.
    const close = new RegExp(`^\\s{0,3}${marker[0]}{${marker.length},}[ \\t]*$`);
    let end = index + 1;
    while (end < lines.length && !close.test(lines[end])) end++;

    const name = extensionNameOfInfo(info);
    if (name) {
      flush();
      segments.push({ kind: "extension", name, body: lines.slice(index + 1, end).join("\n") });
    } else {
      // Any other fenced block is prose: keep it verbatim, fence lines included.
      prose.push(...lines.slice(index, Math.min(end + 1, lines.length)));
    }
    index = end;
  }

  flush();
  return segments;
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
  ...rest
}: {
  label?: string;
  children: ReactNode;
} & Record<`data-${string}`, unknown>) {
  return (
    <div className="my-2 rounded-lg border border-subtle bg-surface" {...rest}>
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
    <ExtensionCard label="Unknown extension" data-extension-unknown>
      <p className="text-[13px] text-fg-secondary">
        Nothing is registered for <code className="font-mono text-fg">radd:{name}</code>. The
        plugin that provides it may be disabled.
      </p>
    </ExtensionCard>
  );
}

export function ExtensionError({ name, error }: { name: string; error: string }) {
  return (
    <ExtensionCard label={`radd:${name}`} data-extension-error>
      <p className="text-[13px] text-status-danger-ink">Could not read this block's parameters: {error}</p>
    </ExtensionCard>
  );
}
