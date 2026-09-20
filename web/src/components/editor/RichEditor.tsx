import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { editorViewCtx } from "@milkdown/kit/core";
import type { Editor } from "@milkdown/kit/core";
import { $view, callCommand, getMarkdown } from "@milkdown/kit/utils";
import { COLLAB_REMOTE_SERIALIZE_MS } from "../../lib/constants";
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
import { collab, collabServiceCtx } from "@milkdown/plugin-collab";
import { cursor } from "@milkdown/kit/plugin/cursor";
import { linkTooltipPlugin } from "@milkdown/kit/component/link-tooltip";
import { listItemBlockComponent } from "@milkdown/kit/component/list-item-block";
import type { Node as ProseNode } from "@milkdown/kit/prose/model";
import { diffComponent, diffDecorationPlugin } from "@milkdown/kit/component/diff";
import { acceptAllDiffsCmd, clearDiffReviewCmd, diff } from "@milkdown/kit/plugin/diff";
import { ProsemirrorAdapterProvider, useNodeViewFactory } from "@prosemirror-adapter/react";
import { Blocks, Sparkles, type LucideIcon } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { aiErrorText, isAiGone } from "../../lib/ai";
import { jiraToMarkdown } from "../../lib/jira-markup";
import { MarkdownSourceCtx } from "../../lib/markdown";
import { searchQuery, usersQuery } from "../../lib/queries";
import { pushToast } from "../../lib/toast";
import { useEditorAi, type AiRun } from "./ai";
import { AiActionPicker } from "./AiActionPicker";
import { ExtensionPicker, insertExtensionBlock } from "./ExtensionPicker";
import { DIFF_CONTROLS_SELECTOR, raddDiffDecoration } from "./diff/decoration-plugin";
import { NO_REVIEW, reviewStatePlugin, type ReviewState } from "./diff/review-state";
import { AiSelectionToolbar } from "./AiSelectionToolbar";
import { AiRunPanel, AiRunStatus, type AiRunView } from "./AiRunPanel";
import { AiRunOutcome, reviewPending, runAi } from "./ai-run";
import { detachedComments, type InlineAnchorRef } from "./detached-comments";
import { NO_SELECTION, selectionRectPlugin, type SelectionRect } from "./selection-state";
import { makeEditor } from "./create-editor";
import { cursorBuilder, selectionBuilder } from "./collab/cursors";
import { COLLAB_FRAGMENT, whenDocumentReady, type CollabConfig } from "./collab/provider";
import { CodeBlockView } from "./CodeBlockView";
import { placeholderPlugin } from "./placeholder";
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
import "./editor.css";
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
  /** Spec 122: bind the document to a live room instead of the local copy.
   *  History is replaced by the Yjs undo manager, the plain-text mode is
   *  unavailable (a textarea cannot bind a CRDT), and `value` is the seed
   *  template. Fixed for the instance's life — a new room means a new `key`. */
  collab?: CollabConfig;
  /** RADD-1274: the open inline comments anchored to this document, so an AI
   *  review can say how many passages it is about to remove. Pages only. */
  inlineAnchors?: InlineAnchorRef[];
  /** Called when a review ends with those passages gone and the person chose
   *  to resolve the comments that pointed at them. */
  onDetachedComments?: (ids: string[]) => void;
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
  disabled = false,
}: {
  icon: LucideIcon;
  title: string;
  className: string;
  onPick: (anchor: DOMRect) => void;
  /** A run or review already owns the editor — a second one is refused
   *  downstream anyway, and a button that only ever earns a toast is worse
   *  than one that says it is unavailable. */
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      // Keep the editor's selection: an AI run applies to it.
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => onPick(event.currentTarget.getBoundingClientRect())}
      className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-fg-secondary transition-colors hover:bg-elevated hover:text-heading focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus disabled:pointer-events-none disabled:opacity-40"
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
 * Obsidian-style WYSIWYG editor (Milkdown/ProseMirror): you type markdown and it renders
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
  collab: collabConfig,
  inlineAnchors,
  onDetachedComments,
  className = "",
  autoFocus = false,
  onSourceChange,
}: RichEditorProps & { onSourceChange: (markdown: string) => void }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const inlineAnchorsRef = useRef(inlineAnchors ?? []);
  inlineAnchorsRef.current = inlineAnchors ?? [];
  const onDetachedRef = useRef(onDetachedComments);
  onDetachedRef.current = onDetachedComments;
  // RADD-1274: what the open review would detach, and whether to resolve it.
  // `preReview` is the document as it stood when the review opened — the
  // answer is decided when the review ENDS, against what was actually
  // accepted, so a Reject all or a hand-picked partial accept never resolves
  // a comment whose passage survived.
  const preReviewDoc = useRef<ProseNode | null>(null);
  const [detached, setDetached] = useState<string[]>([]);
  const [resolveDetached, setResolveDetached] = useState(true);
  const [dropped, setDropped] = useState(0);
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
    () => localStorage.getItem(PLAIN_PREF_KEY) === "1" && !initialAiRun && !collabConfig,
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
  // The AI chrome binds at create time, so the instance must be rebuilt when
  // the gate flips or the curated menu changes — content survives via contentRef.
  const aiSignature = ai
    ? "on:" + ai.actions.map((action) => `${action.id}:${action.label}`).join(",")
    : "off";
  // The live editor, for dispatching AI runs and inserts from React chrome.
  const editorRef = useRef<Editor | null>(null);
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
  // The room binding (spec 122), read the same way: the config is fixed for
  // this instance, and the caller remounts (new `key`) for a new room.
  const collabRef = useRef(collabConfig ?? null);
  collabRef.current = collabConfig ?? null;
  // Typing is refused until the shared document has arrived and is bound —
  // ProseMirror asks this per transaction (see create-editor.ts).
  const collabEditableRef = useRef(!collabConfig);
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
  // Where the selection is, for the floating AI surface (RADD-753).
  const [selectionRect, setSelectionRect] = useState<SelectionRect>(NO_SELECTION);
  // The live AI run — streaming, then reviewing — or null when there is none.
  const [aiRun, setAiRun] = useState<AiRunView | null>(null);
  // What the diff plugin has pending, published from the editor (RADD-762).
  const [review, setReview] = useState<ReviewState>(NO_REVIEW);
  // Which Accept/Reject pair the panel has stepped to; -1 = none yet.
  const [current, setCurrent] = useState(-1);
  const aiHandleRef = useRef<{ cancel: () => void } | null>(null);
  // The table size picker, anchored under the toolbar's table button.
  const [tableMenu, setTableMenu] = useState<{ left: number; top: number } | null>(null);
  // Table operations bound to whichever instance is live. A stable identity, so
  // the node view is not rebuilt when the editor is recreated.
  const tableRun = useMemo(
    () => tableCommands(() => editorRef.current ?? null),
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
  // Same shape for the image view, which needs the surface's uploader to fill an
  // empty node (RADD-760). Read through the ref rather than captured, so a
  // handler that arrives late still works without rebuilding the editor.
  const ImageView = useMemo(
    () => function BoundImageView() {
      return <ImageNodeView upload={uploadRef.current} />;
    },
    [],
  );

  const insertExtension = (spec: PageExtensionSpec) => {
    setExtensionMenu(null);
    editorRef.current?.action((ctx) => insertExtensionBlock(ctx.get(editorViewCtx), spec));
  };

  /** Run one of Milkdown's own commands and give the editor its focus back. */
  const run = (command: Parameters<typeof callCommand>[0], payload?: unknown) => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.action(callCommand(command, payload));
    editor.action((ctx) => ctx.get(editorViewCtx).focus());
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

  /**
   * Stream a transform and land it as a reviewable diff (RADD-753).
   *
   * A direct call, not a command dispatched by NAME. That workaround existed
   * because importing Crepe's `runAICmd` from its subpath bound a second, dead
   * copy of the feature module — and a `$command`'s `.key` is only assigned when
   * its plugin instance runs. Owning the orchestration removes the reason for
   * the trick rather than making the trick tidier.
   */
  const dispatchAiRun = (run: AiRun, range?: { from: number; to: number }) => {
    setAiMenu(null);
    const editor = editorRef.current;
    if (!editor) return;
    editor.action((ctx) => {
      if (reviewPending(ctx)) {
        pushToast("Finish the current AI review first.");
        return;
      }
      const handle = runAi(ctx, run, range);
      aiHandleRef.current = handle;
      setAiRun({ label: run.label, status: AiRunStatus.streaming, text: "" });
      setCurrent(-1);
      handle.onChunk((text) =>
        setAiRun((live) => (live === null ? live : { ...live, text })),
      );
      handle.done
        .then((outcome) => {
          if (outcome === AiRunOutcome.review) {
            const before = ctx.get(editorViewCtx).state.doc;
            const proposed = handle.proposed();
            preReviewDoc.current = before;
            setDetached(proposed ? detachedComments(inlineAnchorsRef.current, before, proposed) : []);
            setResolveDetached(true);
            setDropped(handle.dropped());
            setAiRun((live) =>
              live === null ? live : { ...live, status: AiRunStatus.reviewing },
            );
            return;
          }
          // Stopped, or a reply with nothing in it — either way there is no
          // review to hand over, and the panel should not sit there implying one.
          setAiRun(null);
          if (outcome === AiRunOutcome.empty) pushToast("The AI suggested no changes.");
        })
        .catch((error) => {
          setAiRun(null);
          pushToast(isAiGone(error) ? "AI editor actions are unavailable." : aiErrorText(error));
        })
        .finally(() => {
          aiHandleRef.current = null;
        });
    });
  };

  /**
   * Step to a pending change and mark it as the one being looked at.
   *
   * By DOM rather than by document position: the pairs are widget decorations,
   * so what a person navigates between is the rendered element, and the nth
   * `.milkdown-diff-controls` in the editor is exactly the nth decoration the
   * fork emitted. `data-current` is what lifts it out of the resting state the
   * CSS otherwise keeps them in.
   */
  const navigateReview = (index: number) => {
    const nodes = rootRef.current?.querySelectorAll<HTMLElement>(DIFF_CONTROLS_SELECTOR);
    if (!nodes || nodes.length === 0) return;
    const at = ((index % nodes.length) + nodes.length) % nodes.length;
    nodes.forEach((node, i) => node.toggleAttribute("data-current", i === at));
    nodes[at]?.scrollIntoView({ block: "center", behavior: "smooth" });
    setCurrent(at);
  };

  // The review ending is what closes the panel — including when it ends because
  // someone accepted the last pair by hand rather than pressing Accept all.
  //
  // A changed COUNT invalidates where `current` pointed, in the DOM as well as
  // in state: every accept or reject rebuilds the decoration set from scratch,
  // so the marked element is not the one the number now refers to.
  useEffect(() => {
    setCurrent(-1);
    rootRef.current
      ?.querySelectorAll<HTMLElement>(DIFF_CONTROLS_SELECTOR)
      .forEach((node) => node.removeAttribute("data-current"));
    if (!review.active) {
      setAiRun((live) => (live?.status === AiRunStatus.reviewing ? null : live));
      // RADD-1274: the review is over — against what was ACTUALLY accepted,
      // which comments lost their passage? Only those, and only when asked.
      const before = preReviewDoc.current;
      preReviewDoc.current = null;
      const editor = editorRef.current;
      if (before && editor && resolveDetached && inlineAnchorsRef.current.length > 0) {
        editor.action((ctx) => {
          const after = ctx.get(editorViewCtx).state.doc;
          const ids = detachedComments(inlineAnchorsRef.current, before, after);
          if (ids.length > 0) onDetachedRef.current?.(ids);
        });
      }
      setDetached([]);
      setDropped(0);
    }
  }, [review.active, review.changes]);

  const users = useQuery({ ...usersQuery, enabled: mention?.type === "@" });
  const issues = useQuery({
    ...searchQuery(mention?.query ?? "", MENTION_LIMIT),
    enabled: mention?.type === "#" && Boolean(mention?.query),
  });

  const candidates = useMemo<Candidate[]>(() => {
    if (mention?.type === "@") {
      const needle = mention.query.toLowerCase();
      // Name only (RADD-769): `@` autocomplete reads the member-floor directory,
      // which carries no email. Matching on the address was a nicety; being able
      // to mention a colleague at all without holding `user.manage` is not.
      return (users.data ?? [])
        .filter((user) => user.active !== false && user.name.toLowerCase().includes(needle))
        .slice(0, MENTION_LIMIT)
        .map((user) => ({ label: user.name, href: user.id, sub: "" }));
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
    if (!root || plain) return; // plain mode: the textarea below, no editor instance
    // Feature-flag choices cascade into Crepe's own menus: TopBar entries for image,
    // table and math only render when their feature is enabled. Crepe's BlockEdit
    // slash menu stays OFF: it only duplicated the toolbar's inserts — our own `/`
    // menu (mention.ts trigger + `quickActions`) acts on the ISSUE instead.
    const aiOn = ai !== null;
    const extensionsOn = extensionsRef.current;
    const collabOn = collabRef.current;
    // A recreate (the AI gate resolving) rebinds the room; typing is refused
    // again until it has — the window is a few milliseconds, but a keystroke
    // in it would land in a document about to be replaced.
    if (collabOn) collabEditableRef.current = false;
    let sourceTimer: ReturnType<typeof setTimeout> | undefined;
    // Milkdown directly (RADD-755). Every feature this used to switch off is a
    // React component of ours now, so the wrapper was configuring nothing.
    const editor = makeEditor({
      root,
      value: contentRef.current,
      editable: collabOn ? () => collabEditableRef.current : true,
      // The Yjs undo manager replaces history in a room (spec 122): Mod-z
      // must undo YOUR edits, and the history plugin's keymap, registered
      // first, would otherwise win the key and undo everyone's.
      history: !collabOn,
      onMarkdown: (markdown) => {
        contentRef.current = markdown;
        onChangeRef.current(markdown);
        if (extensionsOn) {
          clearTimeout(sourceTimer);
          sourceTimer = setTimeout(() => onSourceChangeRef.current(markdown), SOURCE_DEBOUNCE_MS);
        }
      },
    });
    // @/#/"/" triggers (before create) — not on anonymous pages: the popups
    // query the user directory / issue search, both logged-in surfaces.
    if (!anonymous) editor.use(mentionProsePlugin(store));
    // Same chip rendering as the read-mode viewer (clicks consumed while editing).
    editor.use(mentionChipsPlugin({ readonly: false, openIssue: () => {} }));
    // Feeds the toolbar's active state (RADD-749). A plugin view, so the snapshot
    // is recomputed from the editor's own updates rather than polled.
    editor.use(toolbarStatePlugin(setSnapshot));
    if (collabOn) editor.use(collab);
    // The chrome Crepe used to wrap, taken from the kit directly (RADD-754).
    editor
      .use(cursor)
      .use(linkTooltipPlugin)
      .use(listItemBlockComponent)
      .use(placeholderPlugin(placeholder ?? "Write…"));
    // Our code block (RADD-752), in BOTH modes — the same view read-only is what
    // keeps code identical in the viewer, which is what RichViewer is for.
    editor.use(
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
    editor.use(
      $view(imageSchema.node, () =>
        nodeViewFactory({
          component: ImageView,
          // The empty state is a form (RADD-760) — a file button and a URL
          // field. Without this ProseMirror reads every keystroke aimed at that
          // field as a keystroke on the document. Scoped to our own chrome, so
          // a click on the image itself still selects the node.
          stopEvent: (event) =>
            event.target instanceof HTMLElement &&
            Boolean(event.target.closest("[data-image-chrome]")),
        }),
      ),
    );
    if (uploadRef.current) {
      editor
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
    editor.use(columnResizingPlugin).use(
      $view(tableSchema.node, () =>
        nodeViewFactory({
          component: TableView,
          // The content element must be a real <tbody> (RADD-759). The adapter
          // defaults it to a <div>, which inside a table is not a row group at
          // all: the rows fell into an anonymous shrink-to-fit table and every
          // table rendered squished, cells at 20px under 213px columns.
          contentAs: "tbody",
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
      editor
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
    editorRef.current = editor;
    let disposed = false;
    let cancelWait: (() => void) | undefined;
    let offRemoteUpdate: (() => void) | undefined;
    let remoteSerializeTimer: ReturnType<typeof setTimeout> | undefined;
    const created = (async () => {
      if (aiOn) {
        // The review machinery, registered by us now that Crepe's AI feature is
        // not doing it: the diff STATE plugin plus our own decoration fork (see
        // diff/decoration-plugin.ts). The upstream decoration component is
        // removed first — with the feature off it is usually absent, and
        // `remove` on something unregistered is a no-op, so this stays correct
        // either way rather than depending on which.
        // `diffComponent` carries the ctx slice our fork reads (labels +
        // customBlockTypes) — Crepe's AI feature used to bring it, and reaching
        // for that slice without it raises "Context not found" before the editor
        // can even create. Its defaults are already Accept/Reject, so it is
        // registered for the SLICE and then has its decoration plugin swapped
        // for ours.
        editor.use(diff).use(diffComponent);
        await editor.remove(diffDecorationPlugin);
        editor
          .use(raddDiffDecoration)
          .use(reviewStatePlugin(setReview))
          .use(selectionRectPlugin(setSelectionRect));
      }
      await editor.create();
      if (collabOn) {
        // The seed rule (spec 122): wait for the room, and only the client
        // the join elected seeds — and only into a fragment that is STILL
        // empty after sync, or two first joiners would double the page.
        const waiting = whenDocumentReady(collabOn);
        cancelWait = waiting.cancel;
        await waiting.ready;
        if (disposed) return;
        editor.action((ctx) => {
          const fragment = collabOn.doc.getXmlFragment(COLLAB_FRAGMENT);
          const service = ctx
            .get(collabServiceCtx)
            .bindXmlFragment(fragment)
            .setAwareness(collabOn.awareness)
            .mergeOptions({ yCursorOpts: { cursorBuilder, selectionBuilder } });
          // The template is the CURRENT markdown (Jira markup converted), not
          // the raw prop — the same text the local copy has been showing.
          if (collabOn.seed && fragment.length === 0) {
            service.applyTemplate(contentRef.current, () => true);
          }
          collabEditableRef.current = true;
          // connect() reconfigures the view, which re-asks `editable`.
          service.connect();
        });
        // Milkdown's listener skips transactions flagged `addToHistory: false`
        // — which is how y-prosemirror applies a REMOTE change — so `onChange`
        // would never learn what the other person typed and the elected saver
        // would serialise a draft that stopped at this client's own edits.
        // Serialise the bound document ourselves after each update — every
        // update, not only the provider's: the origin a remote change carries
        // is the provider's business, and a local burst re-serialising once
        // more 150 ms later is cheaper than a save that misses a colleague.
        const onRemoteUpdate = () => {
          if (disposed) return;
          clearTimeout(remoteSerializeTimer);
          remoteSerializeTimer = setTimeout(() => {
            if (disposed) return;
            const markdown = editor.action(getMarkdown());
            contentRef.current = markdown;
            onChangeRef.current(markdown);
          }, COLLAB_REMOTE_SERIALIZE_MS);
        };
        collabOn.doc.on("update", onRemoteUpdate);
        offRemoteUpdate = () => {
          clearTimeout(remoteSerializeTimer);
          collabOn.doc.off("update", onRemoteUpdate);
        };
      }
      if (autoFocus) root.querySelector<HTMLElement>(".ProseMirror")?.focus();
      // Read-mode transform hand-off: run once, on the first instance that has
      // AI (the first mount often precedes the AI gate queries resolving).
      const run = initialAiRunRef.current;
      if (aiOn && run) {
        initialAiRunRef.current = null;
        dispatchAiRun(run);
      }
    })();
    return () => {
      clearTimeout(sourceTimer);
      disposed = true;
      cancelWait?.();
      offRemoteUpdate?.();
      // Destroy only after create resolves, so an unmount mid-init can't race.
      // In a room, unbind first: the provider outlives this editor for a
      // moment (the parent closes it after the final save), and a remote
      // update or awareness change landing on a destroyed context throws.
      void created.then(() => {
        if (collabOn) {
          try {
            editor.action((ctx) => ctx.get(collabServiceCtx).disconnect());
          } catch {
            // Already torn down — nothing left to unbind.
          }
        }
        editor.destroy();
      });
      if (editorRef.current === editor) editorRef.current = null;
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
      return next; // plain → rich: the effect reseeds the editor from contentRef
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
            {/* Toolbar + AI band travel together, so both stay reachable in a
                long document. The wrapper carries the stickiness: the toolbar's
                own `sticky top-0` then has no room to move inside it, which is
                what keeps the two from sliding over each other. */}
            <div className="sticky top-0 z-[5]">
              {/* Ours (RADD-749). Outside the editor root: ProseMirror owns that
                  node's DOM, so React children inside it would be fought over. */}
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
                        disabled={aiRun !== null}
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
              {ai && aiRun && (
                <AiRunPanel
                  run={aiRun}
                  changes={review.changes}
                  current={current}
                  onNavigate={navigateReview}
                  onStop={() => aiHandleRef.current?.cancel()}
                  onAcceptAll={() => run(acceptAllDiffsCmd.key)}
                  onRejectAll={() => run(clearDiffReviewCmd.key)}
                  detached={detached.length}
                  resolveDetached={resolveDetached}
                  onResolveDetachedChange={setResolveDetached}
                  dropped={dropped}
                />
              )}
            </div>
            {/* ProseMirror owns this node's DOM — keep it free of React children (popup is portaled). */}
            <div ref={rootRef} />
          </>
        )}
        {/* GitLab-style mode bar: same markdown either way, pick your editing surface. */}
        <div className="flex items-center justify-between border-t border-subtle px-2.5 py-1">
          {collabConfig ? (
            // A textarea cannot bind a CRDT: the plain mode is not offered in
            // a room rather than offered and refused.
            <span className="text-[11px] text-fg-muted">Editing together</span>
          ) : (
            <button
              type="button"
              onClick={togglePlain}
              className="cursor-pointer text-[11px] text-fg-muted hover:text-fg hover:underline"
            >
              {plain ? "Switch to rich text editing" : "Switch to plain text editing"}
            </button>
          )}
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
              data-ai-toolbar-menu
            >
              <AiActionPicker actions={ai.actions} onPick={dispatchAiRun} autoFocus />
            </div>
          </>,
          document.body,
        )}
      {ai && (
        <AiSelectionToolbar
          rect={selectionRect}
          actions={ai.actions}
          onRun={dispatchAiRun}
          busy={aiRun !== null}
        />
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
