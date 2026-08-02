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
 * Split a page body into prose runs and extension blocks (RADD-709).
 *
 * This is the whole render strategy, and it is worth saying why. Page bodies are
 * rendered by Crepe (Milkdown/ProseMirror), not by react-markdown — Crepe owns
 * `code_block` with its own node view, so an extension cannot simply be a React
 * component swapped in at the markdown-AST level the way it could in a plain
 * markdown renderer. The two ways out were:
 *
 *  - **A custom Milkdown node** with a React node view, plus a remark transform
 *    turning `radd:*` fences into it. Faithful to ProseMirror, and considerable
 *    machinery: a schema node, a parser rule, a serializer rule and a portal
 *    bridge, all to end up with a React subtree that then has to re-obtain the
 *    router, the query client and the page context it lost crossing the portal.
 *  - **Segmenting the source** — what this does. The body is cut at extension
 *    fences; prose runs render through the same Crepe instance type as before,
 *    and extensions render as ordinary React in the ordinary tree, so context,
 *    routing and data fetching all simply work.
 *
 * Segmenting costs one editor instance per prose run. A page with no extensions
 * — nearly all of them — gets exactly one, which is what it had before this
 * existed; a page with two extensions gets three. That is the trade accepted.
 *
 * Fence tracking is real, not a regex sweep: a ```` ```radd:toc ```` written
 * INSIDE a ```` ```markdown ```` example block is documentation, not an
 * extension, and must render as the code it is.
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
      <p className="text-[13px] text-red-400">Could not read this block's parameters: {error}</p>
    </ExtensionCard>
  );
}
