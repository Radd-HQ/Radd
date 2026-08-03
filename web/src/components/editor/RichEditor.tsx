import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Crepe, CrepeFeature } from "@milkdown/crepe";
import { editorViewCtx } from "@milkdown/kit/core";
import { $view, callCommand } from "@milkdown/kit/utils";
import {
  createCodeBlockCommand,
  insertImageCommand,
  toggleEmphasisCommand,
  toggleInlineCodeCommand,
  toggleLinkCommand,
  toggleStrongCommand,
  turnIntoTextCommand,
  wrapInBlockquoteCommand,
  wrapInBulletListCommand,
  wrapInHeadingCommand,
  wrapInOrderedListCommand,
} from "@milkdown/kit/preset/commonmark";
import { codeBlockSchema, imageSchema } from "@milkdown/kit/preset/commonmark";
import {
  columnResizingPlugin,
  insertTableCommand,
  tableSchema,
  toggleStrikethroughCommand,
} from "@milkdown/kit/preset/gfm";
import { upload, uploadConfig } from "@milkdown/kit/plugin/upload";
import type { Node as ProseNode } from "@milkdown/kit/prose/model";
import { diffDecorationPlugin } from "@milkdown/kit/component/diff";
import { ProsemirrorAdapterProvider, useNodeViewFactory } from "@prosemirror-adapter/react";
import { Blocks, Sparkles, type LucideIcon } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { aiErrorText, isAiGone } from "../../lib/ai";
import { jiraToMarkdown } from "../../lib/jira-markup";
import { MarkdownSourceCtx } from "../../lib/markdown";
import { searchQuery, usersQuery } from "../../lib/queries";
import { pushToast } from "../../lib/toast";
import {
  buildSuggestions,
  createAiProvider,
  runAiOnEditor,
  useEditorAi,
  type AiRun,
} from "./ai";
import { AiActionPicker } from "./AiActionPicker";
import { ExtensionPicker, insertExtensionBlock } from "./ExtensionPicker";
import { raddDiffDecoration } from "./diff/decoration-plugin";
import { CodeBlockView } from "./CodeBlockView";
import { ImageNodeView } from "./ImageNodeView";
import { TableGridPicker } from "./TableGridPicker";
import { TableNodeView } from "./TableNodeView";
import { tableCommands } from "./table-commands";
import { EditorToolbar, ToolbarAction, type ToolbarActionValue } from "./Toolbar";
import { EMPTY_SNAPSHOT, toolbarStatePlugin, type ToolbarSnapshot } from "./toolbar-state";
import {
  raddExtensionConfigOnInsert,
  raddExtensionRemark,
  raddExtensionSchema,
} from "./extension-node";
import { ExtensionNodeView } from "./ExtensionNodeView";
import {
  insertMention,
  mentionProsePlugin,
  removeTrigger,
  type MentionQuery,
  type MentionStore,
} from "./mention";
import { mentionChipsPlugin } from "./chips";
import { PlainEditor, type PlainEditorApi } from "./PlainEditor";
import type { QuickAction } from "../items/quick-actions";
import type { PageExtensionSpec } from "../../lib/types";
import "@milkdown/crepe/theme/common/style.css";
import "@milkdown/crepe/theme/classic-dark.css";
import "./rich-editor.css";

interface RichEditorProps {
  /** Show the "Insert extension" toolbar button (RADD-709). Pages only: an
   *  extension block is page-relative — a `toc` inside an issue comment has no
   *  page whose headings it could list — so the button is opt-in rather than
   *  everywhere. */
  extensions?: boolean;
  /** Initial markdown — the editor is uncontrolled after mount. To reseed with new
   * content (switch doc / clear after submit), remount via a changing `key`. */
  value: string;
  /** Fires on every edit with the current markdown. */
  onChange: (markdown: string) => void;
  placeholder?: string;
  /** Cmd/Ctrl+Enter (composer submit). */
  onSubmitShortcut?: () => void;
  /** Upload a pasted/inserted image and resolve to its URL (wires Crepe's ImageBlock
   * to the app's attachment upload). Omit to disable image insertion entirely. */
  onUploadImage?: (file: File) => Promise<string>;
  /** `/` quick-action menu entries (assign, state, labels, manual automations…) —
   * actions on the issue in context, NOT text inserts (the toolbar covers those).
   * Omit where there's no issue context (pages, new-item modal): `/` stays inert. */
  quickActions?: QuickAction[];
  /** Run this AI transform over the whole document as soon as the editor is
   * ready (read-mode AI menu → edit-with-pending-diff). Consumed once. */
  initialAiRun?: AiRun;
  /** The page has NO session (the public tokened form): skip every authed
   * affordance wholesale — the editor-AI gate queries (each would bounce the
   * visitor to /login via the api client's 401 redirect) and the `@`/`#`/`/`
   * triggers (the user directory and issue search are logged-in surfaces).
   * Formatting only. */
  anonymous?: boolean;
  className?: string;
  autoFocus?: boolean;
}

/** GitLab-style editing-mode preference, sticky across all editors + sessions. */
const PLAIN_PREF_KEY = "radd.editor.plainText";

/**
 * A toolbar button that opens a popover rather than running a command.
 *
 * The class is the handle its popover anchors to, and the handle the render
 * proofs already look for — `svg.radd-ai-toolbar-icon` and
 * `svg.radd-extension-toolbar-icon` were the selectors when these were raw SVG
 * strings handed to a third-party toolbar builder. Keeping them means the proofs
 * assert the same rendered output across the change, which is the point of them.
 */
function ToolbarExtraButton({
  icon: Icon,
  title,
  className,
  onPick,
}: {
  icon: LucideIcon;
  title: string;
  className: string;
  onPick: (anchor: DOMRect) => void;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      // Keep the editor's selection: an AI run applies to it.
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => onPick(event.currentTarget.getBoundingClientRect())}
      className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-fg-secondary transition-colors hover:bg-elevated hover:text-heading focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
    >
      <Icon size={16} className={className} aria-hidden />
    </button>
  );
}

interface Candidate {
  label: string;
  href: string;
  sub: string;
}

const MENTION_LIMIT = 6;

/** How long to let typing settle before a live `radd:toc` re-reads the doc. */
const SOURCE_DEBOUNCE_MS = 300;

/**
 * Obsidian-style WYSIWYG editor (Milkdown/Crepe): you type markdown and it renders
 * live, but the value in and out is always **markdown** — so nothing else in the app
 * (storage, rendering, search) has to change. A fixed TopBar toolbar inserts blocks;
 * `@` autocompletes people, `#` autocompletes issues (emitting the same
 * `@[Name](uuid)` / `#[KEY](KEY)` tokens the reader renders). Reused by pages + comments.
 *
 * The provider is the React half of the node-view bridge (RADD-746): a
 * ProseMirror node view rendered as a PORTAL into this tree keeps the router,
 * the query client and the page context it would otherwise lose crossing into
 * editor-owned DOM. It renders no element of its own — four context providers
 * and the portal list — so it costs nothing on a surface with no node views.
 *
 * `MarkdownSourceCtx` sits ABOVE it on purpose, and the reason is easy to get
 * wrong: the adapter renders its portals as a SIBLING of `children`, so a
 * provider inside the inner component would not reach them. A live `radd:toc`
 * reads its headings from that context, so it has to wrap the portal list, not
 * the editor.
 */
export function RichEditor(props: RichEditorProps) {
  // The live markdown, for extensions that read the document they sit in.
  const [source, setSource] = useState(() => jiraToMarkdown(props.value));
  return (
    <MarkdownSourceCtx.Provider value={source}>
      <ProsemirrorAdapterProvider>
        <RichEditorInner {...props} onSourceChange={setSource} />
      </ProsemirrorAdapterProvider>
    </MarkdownSourceCtx.Provider>
  );
}

function RichEditorInner({
  value,
  onChange,
  placeholder,
  onSubmitShortcut,
  onUploadImage,
  quickActions,
  initialAiRun,
  anonymous = false,
  extensions = false,
  className = "",
  autoFocus = false,
  onSourceChange,
}: RichEditorProps & { onSourceChange: (markdown: string) => void }) {
  const rootRef = useRef<HTMLDivElement>(null);
  // Latest callbacks without recreating the editor (create-once, uncontrolled).
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onSubmitRef = useRef(onSubmitShortcut);
  onSubmitRef.current = onSubmitShortcut;
  const uploadRef = useRef(onUploadImage);
  uploadRef.current = onUploadImage;
  // The CURRENT markdown (seeded from `value` with Jira pages markup converted so old
  // content edits as proper WYSIWYG; updated on every edit) — the source of truth
  // when switching between rich and plain modes.
  const contentRef = useRef(jiraToMarkdown(value));
  // GitLab-style plain-markdown mode: a plain textarea over the same markdown value.
  // An initial AI run needs the rich surface (the diff review is ProseMirror
  // decorations), so it overrides the sticky plain preference for this mount.
  const [plain, setPlain] = useState(
    () => localStorage.getItem(PLAIN_PREF_KEY) === "1" && !initialAiRun,
  );
  const [plainDraft, setPlainDraft] = useState(() => contentRef.current);
  // Stable bridge to the ProseMirror mention plugin (its handlers are reassigned below).
  const storeRef = useRef<MentionStore>({ view: null, onQuery: () => {}, keydown: () => false });
  const store = storeRef.current;
  // Same bridge for plain mode (text splicing instead of ProseMirror transactions).
  const plainApiRef = useRef<PlainEditorApi | null>(null);

  const [mention, setMention] = useState<MentionQuery | null>(null);
  const [index, setIndex] = useState(0);

  // Editor AI (spec 103): non-null only once the instance feature, the user's
  // preference AND the fetched action menu all line up (see useEditorAi).
  // Anonymous pages never even ask — the gate queries are authenticated.
  const ai = useEditorAi(!anonymous);
  // Suggestions bind at Crepe create time, so the instance must be rebuilt when
  // the gate flips or the curated menu changes — content survives via contentRef.
  const aiSignature = ai
    ? "on:" + ai.actions.map((action) => `${action.id}:${action.label}`).join(",")
    : "off";
  // The live Crepe instance, for dispatching AI runs from React chrome.
  const crepeRef = useRef<Crepe | null>(null);
  // The toolbar AI popover, anchored under the TopBar's AI button when open.
  const [aiMenu, setAiMenu] = useState<{ left: number; top: number } | null>(null);
  // The extension insert popover, anchored under its own TopBar button.
  const [extensionMenu, setExtensionMenu] = useState<{ left: number; top: number } | null>(null);
  // Consumed once — survives the gate-flip recreate (the first instance often
  // mounts before the AI queries resolve, without the AI feature).
  const initialAiRunRef = useRef(initialAiRun ?? null);
  // Read inside the create effect, which must not re-run when the flag changes
  // identity — it is a static per-surface choice, not live state.
  const extensionsRef = useRef(extensions);
  extensionsRef.current = extensions;
  // Builds a ProseMirror node view whose body is a React portal into this tree.
  const nodeViewFactory = useNodeViewFactory();
  // Publishing the live markdown is only worth it on surfaces that HAVE
  // extensions: elsewhere it would re-render the chrome on every keystroke to
  // feed nothing. Debounced for the same reason — a toc rebuilding per
  // character is work nobody can see.
  const onSourceChangeRef = useRef(onSourceChange);
  onSourceChangeRef.current = onSourceChange;
  // What the toolbar lights up. Published by a plugin view only when it CHANGES,
  // so typing inside one paragraph does not re-render the chrome per keystroke.
  const [snapshot, setSnapshot] = useState<ToolbarSnapshot>(EMPTY_SNAPSHOT);
  // The table size picker, anchored under the toolbar's table button.
  const [tableMenu, setTableMenu] = useState<{ left: number; top: number } | null>(null);
  // Table operations bound to whichever instance is live. A stable identity, so
  // the node view is not rebuilt when the editor is recreated.
  const tableRun = useMemo(
    () => tableCommands(() => crepeRef.current?.editor ?? null),
    [],
  );
  // The node view takes no props of its own; the runner is closed over here so
  // the component stays a plain `ComponentType<Record<string, never>>`, which is
  // what the adapter's factory expects.
  const TableView = useMemo(
    () => function BoundTableView() {
      return <TableNodeView run={tableRun} />;
    },
    [tableRun],
  );

  const insertExtension = (spec: PageExtensionSpec) => {
    setExtensionMenu(null);
    crepeRef.current?.editor.action((ctx) => insertExtensionBlock(ctx.get(editorViewCtx), spec));
  };

  /** Run one of Milkdown's own commands and give the editor its focus back. */
  const run = (command: Parameters<typeof callCommand>[0], payload?: unknown) => {
    const crepe = crepeRef.current;
    if (!crepe) return;
    crepe.editor.action(callCommand(command, payload));
    crepe.editor.action((ctx) => ctx.get(editorViewCtx).focus());
  };

  const onToolbarAction = (action: ToolbarActionValue, anchor: DOMRect) => {
    switch (action) {
      case ToolbarAction.bold:
        return run(toggleStrongCommand.key);
      case ToolbarAction.italic:
        return run(toggleEmphasisCommand.key);
      case ToolbarAction.strike:
        return run(toggleStrikethroughCommand.key);
      case ToolbarAction.inlineCode:
        return run(toggleInlineCodeCommand.key);
      case ToolbarAction.link:
        // An empty href on purpose: the link tooltip is what asks for the URL,
        // and pre-filling it with a placeholder would have to be deleted first.
        return run(toggleLinkCommand.key, { href: "" });
      case ToolbarAction.bulletList:
        return run(wrapInBulletListCommand.key);
      case ToolbarAction.orderedList:
        return run(wrapInOrderedListCommand.key);
      case ToolbarAction.quote:
        return run(wrapInBlockquoteCommand.key);
      case ToolbarAction.codeBlock:
        return run(createCodeBlockCommand.key);
      case ToolbarAction.image:
        return run(insertImageCommand.key);
      case ToolbarAction.table:
        // Not an immediate insert: sweep a grid for the size (RADD-750). A fixed
        // default is a shape you then have to correct.
        return setTableMenu({
          left: Math.min(anchor.left, window.innerWidth - 240),
          top: anchor.bottom + 4,
        });
    }
  };

  /** 0 = paragraph, 1–3 = heading. */
  const onHeading = (level: number) =>
    level === 0 ? run(turnIntoTextCommand.key) : run(wrapInHeadingCommand.key, level);

  const dispatchAiRun = (run: AiRun) => {
    setAiMenu(null);
    crepeRef.current?.editor.action((ctx) => {
      if (!runAiOnEditor(ctx, run)) pushToast("Finish the current AI review first.");
    });
  };

  const users = useQuery({ ...usersQuery, enabled: mention?.type === "@" });
  const issues = useQuery({
    ...searchQuery(mention?.query ?? "", MENTION_LIMIT),
    enabled: mention?.type === "#" && Boolean(mention?.query),
  });

  const candidates = useMemo<Candidate[]>(() => {
    if (mention?.type === "@") {
      const needle = mention.query.toLowerCase();
      return (users.data ?? [])
        .filter(
          (user) =>
            user.active !== false &&
            (user.name.toLowerCase().includes(needle) || user.email.toLowerCase().includes(needle)),
        )
        .slice(0, MENTION_LIMIT)
        .map((user) => ({ label: user.name, href: user.id, sub: user.email }));
    }
    if (mention?.type === "#") {
      return (issues.data?.results ?? [])
        .slice(0, MENTION_LIMIT)
        .map((hit) => ({ label: hit.key, href: hit.key, sub: hit.title }));
    }
    if (mention?.type === "/" && quickActions) {
      // Every typed token must match label+keywords: "/assign hus", "/add lab foo"…
      const tokens = mention.query.toLowerCase().split(/\s+/).filter(Boolean);
      return quickActions
        .filter((action) => {
          const haystack = (action.label + " " + (action.keywords ?? "")).toLowerCase();
          return tokens.every((token) => haystack.includes(token));
        })
        .slice(0, 8)
        .map((action) => ({ label: action.label, href: action.id, sub: action.hint ?? "" }));
    }
    return [];
  }, [mention, users.data, issues.data, quickActions]);

  const safeIndex = candidates.length ? Math.min(index, candidates.length - 1) : 0;

  const accept = (i: number) => {
    const candidate = candidates[i];
    if (!candidate || !mention) return;
    const action =
      mention.type === "/" ? quickActions?.find((entry) => entry.id === candidate.href) : null;
    if (plain) {
      // Plain mode: same tokens/commands, spliced as markdown text.
      const api = plainApiRef.current;
      if (!api) return;
      api.replaceRange(
        mention.from,
        mention.to,
        mention.type === "/" ? "" : `${mention.type}[${candidate.label}](${candidate.href}) `,
      );
    } else {
      if (!store.view) return;
      if (mention.type === "/") {
        // Quick action: the typed `/query` was a command, not content — remove it.
        removeTrigger(store.view, mention);
      } else {
        insertMention(store.view, mention, candidate.label, candidate.href);
      }
    }
    setMention(null);
    void action?.run();
  };

  // Reassign each render so the plugin's handlers always see current state.
  store.onQuery = (query) => {
    setMention(query);
    setIndex(0);
  };
  store.keydown = (action) => {
    if (!mention) return false;
    if (action === "escape") {
      // Always dismissible — even while the popup only shows a hint/empty state.
      setMention(null);
      return true;
    }
    if (candidates.length === 0) return false; // let Enter/arrows act normally
    if (action === "down") setIndex((i) => (i + 1) % candidates.length);
    else if (action === "up") setIndex((i) => (i - 1 + candidates.length) % candidates.length);
    else if (action === "enter") accept(safeIndex);
    return true;
  };

  useEffect(() => {
    const root = rootRef.current;
    if (!root || plain) return; // plain mode: the textarea below, no Crepe instance
    // Feature-flag choices cascade into Crepe's own menus: TopBar entries for image,
    // table and math only render when their feature is enabled. Crepe's BlockEdit
    // slash menu stays OFF: it only duplicated the toolbar's inserts — our own `/`
    // menu (mention.ts trigger + `quickActions`) acts on the ISSUE instead.
    // The floating selection Toolbar rides the AI gate: it is where Crepe puts the
    // AI entry point (spec 103); without AI it would only duplicate the TopBar.
    const aiOn = ai !== null;
    const extensionsOn = extensionsRef.current;
    const crepe = new Crepe({
      root,
      defaultValue: contentRef.current,
      features: {
        // Ours now (RADD-749) — rendered above this root as real React.
        [CrepeFeature.TopBar]: false,
        [CrepeFeature.Toolbar]: aiOn,
        [CrepeFeature.BlockEdit]: false,
        // Ours now (RADD-751): the image node view carries the resize handle, and
        // paste/drop upload moves to @milkdown/plugin-upload below. Crepe's block
        // image was a second node type for the same markdown, which is one more
        // thing that would have had to be untangled at removal time.
        [CrepeFeature.ImageBlock]: false,
        [CrepeFeature.AI]: aiOn,
        [CrepeFeature.Latex]: false,
        // Ours now (RADD-752) — CodeMirror wired directly, so we own when a
        // <pre> becomes a .cm-editor rather than discovering it in a proof.
        [CrepeFeature.CodeMirror]: false,
        // Ours now (RADD-750). The ENGINE is untouched: prosemirror-tables is
        // what every ProseMirror editor uses. Only the chrome changes.
        [CrepeFeature.Table]: false,
      },
      featureConfigs: {
        [CrepeFeature.Placeholder]: { text: placeholder ?? "Write…" },
        [CrepeFeature.AI]: {
          provider: createAiProvider(),
          buildAISuggestions: buildSuggestions(ai?.actions ?? []),
          diffReviewOnEnd: true, // stream lands as a reviewable diff, never a silent replace
          onError: (error) => {
            // Crepe wraps whatever the provider threw; our ApiError is the cause.
            const cause = error.cause ?? error;
            pushToast(isAiGone(cause) ? "AI editor actions are unavailable." : aiErrorText(cause));
          },
        },
      },
    });
    // @/#/"/" triggers (before create) — not on anonymous pages: the popups
    // query the user directory / issue search, both logged-in surfaces.
    if (!anonymous) crepe.editor.use(mentionProsePlugin(store));
    // Same chip rendering as the read-mode viewer (clicks consumed while editing).
    crepe.editor.use(mentionChipsPlugin({ readonly: false, openIssue: () => {} }));
    // Feeds the toolbar's active state (RADD-749). A plugin view, so the snapshot
    // is recomputed from the editor's own updates rather than polled.
    crepe.editor.use(toolbarStatePlugin(setSnapshot));
    // Our code block (RADD-752), in BOTH modes — the same view read-only is what
    // keeps code identical in the viewer, which is what RichViewer is for.
    crepe.editor.use(
      $view(codeBlockSchema.node, () =>
        nodeViewFactory({
          component: CodeBlockView,
          // CodeMirror owns every key inside the block; ProseMirror must not
          // also try to interpret them. The escape keys are handled inside.
          stopEvent: () => true,
        }),
      ),
    );
    // Resizable images (RADD-751), plus paste/drop upload. Registered whether or
    // not this surface can upload: an image that ARRIVED some other way still
    // resizes, and a comment is as likely to hold a screenshot as a page is.
    crepe.editor.use(
      $view(imageSchema.node, () => nodeViewFactory({ component: ImageNodeView })),
    );
    if (uploadRef.current) {
      crepe.editor
        .use(upload)
        .config((ctx) =>
          ctx.update(uploadConfig.key, (base) => ({
            ...base,
            uploader: async (files, schema) => {
              const nodes: ProseNode[] = [];
              for (const file of Array.from(files)) {
                if (!file.type.startsWith("image/")) continue;
                const src = await uploadRef.current?.(file);
                if (!src) continue;
                const node = schema.nodes.image?.createAndFill({ src, alt: file.name });
                if (node) nodes.push(node);
              }
              return nodes;
            },
          })),
        );
    }
    // Table chrome (RADD-750), plus the column-resizing plugin preset-gfm ships
    // but does not compose. Resized widths are a session-only affordance: GFM
    // cannot express a column width, and this body is markdown by design.
    crepe.editor.use(columnResizingPlugin).use(
      $view(tableSchema.node, () =>
        nodeViewFactory({
          component: TableView,
          // The handles are React; the CELLS are ProseMirror's. Only stop what
          // originates in our own chrome, or typing in a cell stops working.
          stopEvent: (event) =>
            event.target instanceof HTMLElement &&
            Boolean(event.target.closest("[data-table-handle]")),
        }),
      ),
    );
    // `radd:*` fences become a real node with a live React view (RADD-746).
    // Registered only where extensions are offered: a comment has no page whose
    // headings a `toc` could list, and turning its fences into rendered blocks
    // there would change what a comment does, not just how it looks.
    if (extensionsOn) {
      crepe.editor
        .use(raddExtensionRemark)
        .use(raddExtensionSchema)
        .use(raddExtensionConfigOnInsert)
        .use(
          $view(raddExtensionSchema.node, () =>
            nodeViewFactory({
              component: ExtensionNodeView,
              // The block is an atom whose body is interactive React — links,
              // buttons, a config dialog. ProseMirror must not treat a click
              // inside it as a click on the document.
              stopEvent: () => true,
            }),
          ),
        );
    }
    let sourceTimer: ReturnType<typeof setTimeout> | undefined;
    crepe.on((listener) => {
      listener.markdownUpdated((_ctx, markdown) => {
        contentRef.current = markdown;
        onChangeRef.current(markdown);
        if (extensionsOn) {
          clearTimeout(sourceTimer);
          sourceTimer = setTimeout(() => onSourceChangeRef.current(markdown), SOURCE_DEBOUNCE_MS);
        }
      });
    });
    crepeRef.current = crepe;
    const created = (async () => {
      if (aiOn) {
        // Per-block AI diff review: swap Crepe's per-chunk decoration plugin
        // for the fork (see diff/decoration-plugin.ts). Pre-create, so the
        // remove is a plain unregister.
        await crepe.editor.remove(diffDecorationPlugin);
        crepe.editor.use(raddDiffDecoration);
      }
      await crepe.create();
      if (autoFocus) root.querySelector<HTMLElement>(".ProseMirror")?.focus();
      // Read-mode transform hand-off: run once, on the first instance that has
      // AI (the first mount often precedes the AI gate queries resolving).
      const run = initialAiRunRef.current;
      if (aiOn && run) {
        initialAiRunRef.current = null;
        crepe.editor.action((ctx) => {
          runAiOnEditor(ctx, run);
        });
      }
    })();
    return () => {
      clearTimeout(sourceTimer);
      // Destroy only after create resolves, so an unmount mid-init can't race.
      void created.then(() => crepe.destroy());
      if (crepeRef.current === crepe) crepeRef.current = null;
    };
    // Recreated on mode switch + AI gate/menu changes — `value` changes are
    // ignored (remount to reseed).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plain, aiSignature]);

  const togglePlain = () => {
    setPlain((current) => {
      const next = !current;
      localStorage.setItem(PLAIN_PREF_KEY, next ? "1" : "0");
      if (next) setPlainDraft(contentRef.current); // rich → plain: show live markdown
      return next; // plain → rich: the effect reseeds Crepe from contentRef
    });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && onSubmitRef.current) {
      event.preventDefault();
      onSubmitRef.current();
    }
  };

  // `#` and `/` popups open immediately with a hint (typing the trigger alone showing
  // nothing reads as "broken" — with `#` it also tempts a `# ` heading).
  const popupHint =
    mention?.type === "#" && candidates.length === 0
      ? mention.query === ""
        ? "Type an issue key or search words…"
        : issues.isFetching
          ? "Searching…"
          : "No matching issues"
      : mention?.type === "/" && quickActions && candidates.length === 0
        ? "No matching actions"
        : null;
  const showPopup = mention !== null && (candidates.length > 0 || popupHint !== null);

  return (
    <>
      <div
        onKeyDown={onKeyDown}
        onBlur={() => setTimeout(() => setMention(null), 150)}
        className={"radd-rich-editor rounded-md border border-strong bg-surface " + className}
      >
        {plain ? (
          <PlainEditor
            value={plainDraft}
            onChange={(markdown) => {
              setPlainDraft(markdown);
              contentRef.current = markdown;
              onChangeRef.current(markdown);
            }}
            placeholder={placeholder ?? "Write…"}
            autoFocus={autoFocus}
            onUploadImage={onUploadImage}
            onQuery={(query) => {
              if (anonymous) return; // no @/#// popups without a session
              setMention(query);
              setIndex(0);
            }}
            onNavKey={(action) => store.keydown(action)}
            apiRef={plainApiRef}
          />
        ) : (
          <>
            {/* Ours (RADD-749). Outside the editor root: Crepe owns that node's
                DOM, so React children inside it would be fought over. */}
            <EditorToolbar
              snapshot={snapshot}
              onAction={onToolbarAction}
              onHeading={onHeading}
              images={Boolean(onUploadImage)}
              tables
              extra={
                <>
                  {ai && (
                    <ToolbarExtraButton
                      icon={Sparkles}
                      title="AI"
                      className="radd-ai-toolbar-icon"
                      onPick={(rect) =>
                        setAiMenu({
                          left: Math.min(rect.left, window.innerWidth - 300),
                          top: rect.bottom + 4,
                        })
                      }
                    />
                  )}
                  {extensions && (
                    <ToolbarExtraButton
                      icon={Blocks}
                      title="Insert extension"
                      className="radd-extension-toolbar-icon"
                      onPick={(rect) =>
                        setExtensionMenu({
                          left: Math.min(rect.left, window.innerWidth - 300),
                          top: rect.bottom + 4,
                        })
                      }
                    />
                  )}
                </>
              }
            />
            {/* Crepe owns this node's DOM — keep it free of React children (popup is portaled). */}
            <div ref={rootRef} />
          </>
        )}
        {/* GitLab-style mode bar: same markdown either way, pick your editing surface. */}
        <div className="flex items-center justify-between border-t border-subtle px-2.5 py-1">
          <button
            type="button"
            onClick={togglePlain}
            className="cursor-pointer text-[11px] text-fg-muted hover:text-fg hover:underline"
          >
            {plain ? "Switch to rich text editing" : "Switch to plain text editing"}
          </button>
          <span
            title="Markdown is supported"
            className="rounded border border-strong px-1 font-mono text-[10px] font-semibold text-fg-muted"
          >
            M↓
          </span>
        </div>
      </div>
      {/* Toolbar AI popover: same curated actions + freeform prompt the
          selection tooltip offers, minus the need for a selection. */}
      {aiMenu &&
        ai &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[59]" onMouseDown={() => setAiMenu(null)} />
            <div
              style={{ position: "fixed", left: aiMenu.left, top: aiMenu.top }}
              className="z-[60] w-72 rounded-md border border-strong bg-surface p-1.5 shadow-pop animate-menu-in"
            >
              <AiActionPicker actions={ai.actions} onPick={dispatchAiRun} autoFocus />
            </div>
          </>,
          document.body,
        )}
      {tableMenu &&
        createPortal(
          <TableGridPicker
            at={tableMenu}
            onDismiss={() => setTableMenu(null)}
            onPick={(rows, cols) => {
              setTableMenu(null);
              // `row` is the TOTAL row count, header included — `createTable`
              // makes row 0 the header. One swept square, one table cell, which
              // is what the grid looks like it is promising.
              run(insertTableCommand.key, { row: rows, col: cols });
            }}
          />,
          document.body,
        )}
      {extensionMenu &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[59]" onMouseDown={() => setExtensionMenu(null)} />
            <ExtensionPicker at={extensionMenu} onPick={insertExtension} />
          </>,
          document.body,
        )}
      {showPopup &&
        createPortal(
          <ul
            style={{ position: "fixed", left: mention.coords.left, top: mention.coords.bottom + 4 }}
            className="z-[60] max-h-56 w-72 overflow-auto rounded-md border border-strong bg-surface shadow-xl"
          >
            {popupHint && (
              <li className="px-2.5 py-1.5 text-[11px] text-fg-muted">{popupHint}</li>
            )}
            {candidates.map((candidate, i) => (
              <li key={candidate.href}>
                <button
                  type="button"
                  // onMouseDown fires before the editor's blur, so the pick lands.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    accept(i);
                  }}
                  className={
                    "flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left cursor-pointer " +
                    (i === safeIndex ? "bg-elevated" : "hover:bg-elevated/60")
                  }
                >
                  <span
                    className={
                      "shrink-0 text-[13px] " +
                      (mention.type === "#"
                        ? "font-mono text-[11px] text-sky-300"
                        : "text-fg")
                    }
                  >
                    {candidate.label}
                  </span>
                  <span className="truncate text-[11px] text-fg-muted">{candidate.sub}</span>
                </button>
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </>
  );
}
