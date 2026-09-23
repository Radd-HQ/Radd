import { createContext, useContext, useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";
import { jiraToMarkdown } from "./jira-markup";
import { headingAnchorId } from "./markdown-outline";
import { MermaidDiagram } from "../components/editor/MermaidDiagram";
import { isMermaid } from "../components/editor/mermaid";
import { useOpenIssueRef } from "./hooks";
import {
  ExtensionError,
  UnknownExtension,
  extensionNameOf,
  lookupPageExtension,
  parseExtensionParams,
} from "./page-extensions";

/**
 * Read-mode markdown renderer. Built on **remark** — the exact parser Milkdown/Crepe
 * serialises to — so anything the editor produces (GFM tables, task lists, strike-
 * through, fenced code, backslash escapes, h1–h6…) round-trips correctly. Renders to
 * React elements only (react-markdown never uses innerHTML and drops raw HTML), so
 * hostile input can't execute.
 *
 * The app's two custom tokens are preserved by a small remark plugin: `@[Name](uuid)`
 * → a mention chip, `#[TD-123](TD-123)` → an issue link to `/issues/TD-123`.
 */

const UUID_RE = /^[0-9a-fA-F-]{36}$/;
const ISSUE_KEY_RE = /^[A-Za-z][A-Za-z0-9]{0,9}-\d+$/;
const BR_RE = /^<br\s*\/?>$/i;

/**
 * Turn `@[Name](uuid)` / `#[KEY](KEY)` (a text `@`/`#` + a link in the mdast) into
 * tagged nodes the component map renders as chips, and turn `<br>` HTML nodes — which
 * editors emit inside table cells (cells can't hold real newlines) and older content
 * may carry — into real line breaks instead of literal `<br />` text. Only `<br>` is
 * converted; any other raw HTML stays inert text (no unsafe HTML rendering).
 */
function remarkRaddTokens() {
  return (tree: unknown) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    visit(tree as any, (node: any) => {
      if (node.type === "html" && BR_RE.test(String(node.value).trim())) {
        node.type = "break";
        delete node.value;
        return;
      }
      const children = node.children;
      if (!Array.isArray(children)) return;
      for (let i = 0; i < children.length; i++) {
        const link = children[i];
        if (link?.type !== "link") continue;
        const prev = children[i - 1];
        const prevText: string | undefined = prev?.type === "text" ? prev.value : undefined;
        if (UUID_RE.test(link.url) && prevText?.endsWith("@")) {
          prev.value = prevText.slice(0, -1);
          link.data = { hName: "span", hProperties: { className: ["radd-mention"] } };
        } else if (ISSUE_KEY_RE.test(link.url) && prevText?.endsWith("#")) {
          prev.value = prevText.slice(0, -1);
          link.data = { hProperties: { className: ["radd-issue-ref"] } };
          link.url = `/issues/${link.url}`;
        }
      }
    });
  };
}

const HEADING = {
  h1: "mt-3 mb-1.5 text-base font-semibold text-heading",
  h2: "mt-3 mb-1 text-[15px] font-semibold text-heading",
  h3: "mt-2.5 mb-1 text-[13px] font-semibold text-fg",
  h4: "mt-2 mb-1 text-[13px] font-semibold text-fg",
  h5: "mt-2 mb-0.5 text-xs font-semibold uppercase tracking-wide text-fg-secondary",
  h6: "mt-2 mb-0.5 text-xs font-semibold uppercase tracking-wide text-fg-muted",
} as const;

/**
 * Real heading elements (they were spans), each carrying an anchor id derived
 * from its text — which is what lets `radd:toc` link INTO the document and what
 * gives the page an outline for screen readers (RADD-710). The id must be
 * allocated by the same walk the outline uses, so duplicate headings agree.
 */
const heading = (cls: string, level: number) =>
  function Heading({ children }: { children?: ReactNode }) {
    const seen = useContext(HeadingIdCtx);
    const text = textOf(children);
    const id = useMemo(() => headingAnchorId(text, seen), [text, seen]);
    const Tag = `h${level}` as "h1";
    return (
      <Tag id={id} className={"block scroll-mt-16 " + cls}>
        {children}
      </Tag>
    );
  };

/** Flatten a React children tree to its text, for the anchor id. */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  const props = (node as { props?: { children?: ReactNode } }).props;
  return props ? textOf(props.children) : "";
}

/** Per-render duplicate counter, so `## Setup` twice yields setup / setup-2. */
const HeadingIdCtx = createContext<Map<string, number>>(new Map());

/** The markdown SOURCE of the current render — `radd:toc` reads headings from
 *  it, because the rendered tree does not exist yet when the block renders. */
export const MarkdownSourceCtx = createContext<string>("");

const components = {
  h1: heading(HEADING.h1, 1),
  h2: heading(HEADING.h2, 2),
  h3: heading(HEADING.h3, 3),
  h4: heading(HEADING.h4, 4),
  h5: heading(HEADING.h5, 5),
  h6: heading(HEADING.h6, 6),
  p: ({ children }: { children?: ReactNode }) => <p className="my-1.5">{children}</p>,
  a: ({ href, className, children }: { href?: string; className?: string; children?: ReactNode }) => {
    if (className?.includes("radd-issue-ref")) {
      return <IssueRefChip href={href}>{children}</IssueRefChip>;
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-accent-text underline decoration-accent-text/40 hover:decoration-accent-text"
      >
        {children}
      </a>
    );
  },
  span: ({ className, children }: { className?: string; children?: ReactNode }) =>
    className?.includes("radd-mention") ? (
      <span className="rounded bg-accent/15 px-1 py-px font-medium text-accent-text">
        @{children}
      </span>
    ) : (
      <span className={className}>{children}</span>
    ),
  code: ({ className, children }: { className?: string; children?: ReactNode }) => {
    const isInline = !className && !String(children).includes("\n");
    return isInline ? (
      <code className="rounded bg-elevated px-1 py-px font-mono text-[0.85em] text-fg">
        {children}
      </code>
    ) : (
      <code className={className}>{children}</code>
    );
  },
  // A ```radd:<name> fence is an EXTENSION (RADD-709), not code: intercepted
  // here rather than in `code` so the <pre> chrome never wraps it.
  pre: ({ children }: { children?: ReactNode }) => {
    const block = extensionBlockOf(children);
    if (block) return <ExtensionBlock name={block.name} body={block.body} />;
    // A ```mermaid fence is a DIAGRAM here too, not just in the wiki editor: a
    // comment or an issue description that draws one should draw it.
    const diagram = mermaidSourceOf(children);
    if (diagram !== null) return <MermaidDiagram source={diagram} />;
    return (
      <pre className="my-2 overflow-x-auto rounded-md border border-subtle bg-surface p-2.5 font-mono text-xs text-fg">
        {children}
      </pre>
    );
  },
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="my-2 border-l-2 border-strong pl-3 text-fg-secondary">{children}</blockquote>
  ),
  ul: ({ className, children }: { className?: string; children?: ReactNode }) => (
    <ul
      className={
        "my-1.5 flex flex-col gap-0.5 " +
        (className?.includes("contains-task-list") ? "list-none pl-1" : "list-disc pl-5")
      }
    >
      {children}
    </ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-1.5 flex list-decimal flex-col gap-0.5 pl-5">{children}</ol>
  ),
  li: ({ className, children }: { className?: string; children?: ReactNode }) => (
    <li
      className={
        className?.includes("task-list-item")
          ? // RADD-1296: a done item reads as done — struck through, quieter.
            "list-none [&:has(>input:checked)]:text-fg-muted [&:has(>input:checked)]:line-through"
          : ""
      }
    >
      {children}
    </li>
  ),
  input: ({ checked }: { checked?: boolean }) => (
    <input
      type="checkbox"
      checked={Boolean(checked)}
      readOnly
      className="mr-1.5 size-4 accent-accent align-[-3px]"
    />
  ),
  del: ({ children }: { children?: ReactNode }) => (
    <del className="text-fg-muted line-through">{children}</del>
  ),
  hr: () => <hr className="my-3 border-subtle" />,
  img: ({ src, alt }: { src?: string; alt?: string }) => (
    <a href={src} target="_blank" rel="noreferrer" className="block max-w-md">
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className="my-1 max-h-80 max-w-full rounded-md border border-subtle object-contain"
      />
    </a>
  ),
  table: ({ children }: { children?: ReactNode }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="border border-emphasis bg-elevated px-2 py-1 text-left font-semibold text-heading">
      {children}
    </th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="border border-emphasis px-2 py-1 align-top">{children}</td>
  ),
};

/**
 * Pull `{name, body}` out of a <pre>'s single <code> child when its language is
 * `radd:<name>`. Returns null for ordinary code, which is the common case.
 */
function extensionBlockOf(
  children: ReactNode,
): { name: string; body: string } | null {
  const only = Array.isArray(children) ? children[0] : children;
  const props = (only as { props?: { className?: string; children?: ReactNode } })?.props;
  if (!props) return null;
  const name = extensionNameOf(props.className);
  if (!name) return null;
  return { name, body: textOf(props.children) };
}

/**
 * The source of a ```` ```mermaid ```` fence, or null for ordinary code.
 *
 * react-markdown puts the info string on the inner `<code>` as
 * `language-mermaid`, so the check reads the same class the highlighter would.
 */
function mermaidSourceOf(children: ReactNode): string | null {
  const only = Array.isArray(children) ? children[0] : children;
  const props = (only as { props?: { className?: string; children?: ReactNode } })?.props;
  if (!props) return null;
  const language = /language-([\w-]+)/.exec(props.className ?? "")?.[1] ?? "";
  return isMermaid(language) ? textOf(props.children) : null;
}


function ExtensionBlock({ name, body }: { name: string; body: string }) {
  const extension = lookupPageExtension(name);
  if (!extension) return <UnknownExtension name={name} />;
  const parsed = parseExtensionParams(body);
  if (!parsed.ok) return <ExtensionError name={name} error={parsed.error} />;
  return <>{extension.render(parsed.params)}</>;
}

/**
 * An issue reference inside rendered markdown (RADD-711). A plain click opens
 * the PEEK panel over whatever you are reading — a wiki page is usually the
 * thing you were reading *for* the references, so following one should not cost
 * you the page. It keeps its real href, so cmd/middle-click still opens a tab.
 *
 * Same rule as the issue page's child rows (RADD-699), via the same helper.
 */
function IssueRefChip({ href, children }: { href?: string; children?: ReactNode }) {
  const openRef = useOpenIssueRef();
  const key = (href ?? "").replace(/^\/issues\//, "");
  return (
    <a
      href={href}
      onClick={(event) => void openRef(key, event)}
      className="cursor-pointer rounded bg-sky-500/15 px-1 py-px font-medium text-sky-300 no-underline hover:bg-sky-500/25"
    >
      {children}
    </a>
  );
}

export function Markdown({ text }: { text: string }) {
  // Backwards-compat: render any Jira pages markup (imported/pasted) as markdown too.
  // No-op on native markdown (none of the Jira patterns occur there).
  const md = useMemo(() => jiraToMarkdown(text), [text]);
  // One counter per render pass, so duplicate headings get stable -2/-3 ids.
  const headingIds = useMemo(() => new Map<string, number>(), [md]);
  return (
    <MarkdownSourceCtx.Provider value={md}>
      <HeadingIdCtx.Provider value={headingIds}>
        <div className="radd-markdown break-words text-[13px] leading-relaxed text-fg">
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkRaddTokens]} components={components}>
            {md}
          </ReactMarkdown>
        </div>
      </HeadingIdCtx.Provider>
    </MarkdownSourceCtx.Provider>
  );
}
