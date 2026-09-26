import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { editorViewCtx } from "@milkdown/kit/core";
import type { Editor } from "@milkdown/kit/core";
import { $prose, $view, callCommand, getMarkdown } from "@milkdown/kit/utils";
import { BOUND_SERIALIZE_MS } from "../../lib/constants";
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
import { cursor } from "@milkdown/kit/plugin/cursor";
import { linkTooltipPlugin } from "@milkdown/kit/component/link-tooltip";
import { listItemBlockComponent } from "@milkdown/kit/component/list-item-block";
import type { Node as ProseNode } from "@milkdown/kit/prose/model";
import { diffComponent, diffDecorationPlugin } from "@milkdown/kit/component/diff";
import { acceptAllDiffsCmd, clearDiffReviewCmd, diff } from "@milkdown/kit/plugin/diff";
import { ProsemirrorAdapterProvider, useNodeViewFactory } from "@prosemirror-adapter/react";
import { Blocks } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { jiraToMarkdown } from "../../lib/jira-markup";
import {
  MarkdownSourceContext,
  Slot,
  SlotId,
  useSlot,
  type BindableEditor,
  type EditorBinding,
  type EditorHandle,
  type EditorRange,
  type EditorTransform,
  type RichEditorProps as SdkRichEditorProps,
} from "@radd/plugin-sdk";
import { entitySearchQuery, searchQuery, usersQuery } from "../../lib/queries";
import { pushToast } from "../../lib/toast";
import { ExtensionPicker, insertExtensionBlock } from "./ExtensionPicker";
import { DIFF_CONTROLS_SELECTOR, raddDiffDecoration } from "./diff/decoration-plugin";
import { NO_REVIEW, reviewStatePlugin, type ReviewState } from "./diff/review-state";
import { SelectionActions } from "./SelectionActions";
import { ToolbarExtraButton } from "./ToolbarExtraButton";
import { TransformRunPanel, TransformRunStatus, type TransformRunView } from "./TransformRunPanel";
import { TransformOutcome, reviewPending, runTransform } from "./transform-run";
import { detachedComments } from "./detached-comments";
import { NO_SELECTION, selectionRectPlugin, type SelectionRect } from "./selection-state";
import { makeEditor } from "./create-editor";
import { bindableEditor, documentChangePlugin } from "./bindable";
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
import type { PageExtensionSpec } from "@radd-plugin-ui/pages/types";
import "./editor.css";
import "./rich-editor.css";

/** The SDK's contract (its docs cover the shared props), minus `attachTo`: the host bridge turns
 *  that into `onUploadImage`. */
interface RichEditorProps extends Omit<SdkRichEditorProps, "attachTo"> {
  /** Cmd/Ctrl+Enter (composer submit). */
  onSubmitShortcut?: () => void;
  /** Upload a pasted/inserted image and resolve to its URL; omit to disable images. */
  onUploadImage?: (file: File) => Promise<string>;
  /** `/` quick-action menu entries (assign, state, labels, manual automations…) —
   * actions on the issue in context, NOT text inserts (the toolbar covers those).
   * Omit where there's no issue context (pages, new-item modal): `/` stays inert. */
  quickActions?: QuickAction[];
  /** The page has NO session (the public tokened form): skip every authed
   * affordance wholesale — the contributed toolbar and selection actions
   * (their gates query authenticated endpoints, and the api client answers a
   * 401 by bouncing the visitor to /login) and the `@`/`#`/`/` triggers (the
   * user directory and issue search are logged-in surfaces). Formatting only. */
  anonymous?: boolean;
  /** The binding brings its own undo, the plain-text mode is unavailable (a textarea cannot
   *  bind), and typing waits for the bind. Fixed for the instance's life — a new binding means a
   *  new `key`. */
  binding?: EditorBinding;
}

/**
 * Bind, unless the editor goes first: resolves the unbind, or undefined once `signal` aborts. A
 * binding that settles after that is unbound at once — its plugins must not outlive the editor.
 */
async function bindUntilAborted(
  binding: EditorBinding,
  editor: BindableEditor,
  signal: AbortSignal,
): Promise<(() => void) | undefined> {
  // Through a promise, so a binding that throws synchronously is a failure, not a crash.
  const bound = Promise.resolve().then(() => binding.bind(editor, signal));
  const aborted = new Promise<undefined>((resolve) => {
    if (signal.aborted) resolve(undefined);
    else signal.addEventListener("abort", () => resolve(undefined), { once: true });
  });
  try {
    const off = await Promise.race([bound, aborted]);
    if (off === undefined) {
      void bound.then((late) => { try { late(); } catch { /* the editor is gone */ } }, () => {});
    }
    return off;
  } catch (error) {
    if (signal.aborted) return undefined;
    // The binding owner reports its own failure (and hands the document back to its ordinary
    // flow); the editor stays read-only rather than accept typing nobody will keep.
    console.error("[radd] the editor's binding failed", error);
    return undefined;
  }
}

/** GitLab-style editing-mode preference, sticky across all editors + sessions. */
const PLAIN_PREF_KEY = "radd.editor.plainText";

interface Candidate {
  label: string;
  href: string;
  sub: string;
}

const MENTION_LIMIT = 6;

/** How long to let typing settle before a live `radd:toc` re-reads the doc. */
const SOURCE_DEBOUNCE_MS = 300;

/**
 * WYSIWYG markdown editor (Milkdown/ProseMirror): markdown in, markdown out, so storage,
 * rendering and search never change. `@` people, `#` issues/entities, `/` quick actions.
 * `ProsemirrorAdapterProvider` renders node views as portals into this React tree.
 * `MarkdownSourceContext` must sit ABOVE it: the adapter renders its portals as a SIBLING of
 * `children`, and a live `radd:toc` reads its headings from that context.
 */
export function RichEditor(props: RichEditorProps) {
  // The live markdown, for extensions that read the document they sit in.
  const [source, setSource] = useState(() => jiraToMarkdown(props.value));
  return (
    <MarkdownSourceContext.Provider value={source}>
      <ProsemirrorAdapterProvider>
        <RichEditorInner {...props} onSourceChange={setSource} />
      </ProsemirrorAdapterProvider>
    </MarkdownSourceContext.Provider>
  );
}

function RichEditorInner({
  value,
  onChange,
  placeholder,
  onSubmitShortcut,
  onUploadImage,
  quickActions,
  initialTransform,
  anonymous = false,
  extensions = false,
  binding,
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
  // What the transform said about its result, shown beside the review.
  const [notes, setNotes] = useState<string[]>([]);
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
  // An initial transform needs the rich surface (the diff review is ProseMirror
  // decorations), so it overrides the sticky plain preference for this mount.
  const [plain, setPlain] = useState(
    () => localStorage.getItem(PLAIN_PREF_KEY) === "1" && !initialTransform && !binding,
  );
  const [plainDraft, setPlainDraft] = useState(() => contentRef.current);
  // Stable bridge to the ProseMirror mention plugin (its handlers are reassigned below).
  const storeRef = useRef<MentionStore>({ view: null, onQuery: () => {}, keydown: () => false });
  const store = storeRef.current;
  // Same bridge for plain mode (text splicing instead of ProseMirror transactions).
  const plainApiRef = useRef<PlainEditorApi | null>(null);

  const [mention, setMention] = useState<MentionQuery | null>(null);
  const [index, setIndex] = useState(0);

  // Contributed editor actions (RADD-1395): toolbar buttons and chrome over a
  // selection, from whichever plugins extend the editor. Anonymous pages offer
  // none — a contribution's gate may query authenticated endpoints.
  const offersActions = !anonymous;
  const selectionContributions = useSlot(SlotId.editorSelectionAction);
  const offersSelectionActions = offersActions && selectionContributions.length > 0;
  // Read by the selection plugin, which is created once per instance: where
  // nothing would float over a selection, moving it re-renders nothing.
  const offersSelectionRef = useRef(offersSelectionActions);
  offersSelectionRef.current = offersSelectionActions;
  // The live editor, for dispatching transforms and inserts from React chrome.
  const editorRef = useRef<Editor | null>(null);
  // The extension insert popover, anchored under its own TopBar button.
  const [extensionMenu, setExtensionMenu] = useState<{ left: number; top: number } | null>(null);
  // Consumed once, by the first instance that finishes creating.
  const initialTransformRef = useRef(initialTransform ?? null);
  // Read inside the create effect, which must not re-run when the flag changes
  // identity — it is a static per-surface choice, not live state.
  const extensionsRef = useRef(extensions);
  extensionsRef.current = extensions;
  // The binding (RADD-1397), read the same way: it is fixed for this
  // instance, and the caller remounts (new `key`) for a new one.
  const bindingRef = useRef(binding ?? null);
  bindingRef.current = binding ?? null;
  // Typing is refused until the binding has bound the document — ProseMirror
  // asks this per transaction (see create-editor.ts).
  const boundRef = useRef(!binding);
  // Builds a ProseMirror node view whose body is a React portal into this tree.
  const nodeViewFactory = useNodeViewFactory();
  const onSourceChangeRef = useRef(onSourceChange);
  onSourceChangeRef.current = onSourceChange;
  // What the toolbar lights up. Published by a plugin view only when it CHANGES,
  // so typing inside one paragraph does not re-render the chrome per keystroke.
  const [snapshot, setSnapshot] = useState<ToolbarSnapshot>(EMPTY_SNAPSHOT);
  // Where the selection is, for the contributed chrome over it (RADD-753).
  const [selectionRect, setSelectionRect] = useState<SelectionRect>(NO_SELECTION);
  // The live transform run — streaming, then reviewing — or null when there is none.
  const [activeRun, setActiveRun] = useState<TransformRunView | null>(null);
  // What the diff plugin has pending, published from the editor (RADD-762).
  const [review, setReview] = useState<ReviewState>(NO_REVIEW);
  // Which Accept/Reject pair the panel has stepped to; -1 = none yet.
  const [current, setCurrent] = useState(-1);
  const runHandleRef = useRef<{ cancel: () => void } | null>(null);
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

  /** Run a contributed transform and land it as a reviewable diff. */
  const dispatchTransform = (transform: EditorTransform, range?: EditorRange) => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.action((ctx) => {
      if (reviewPending(ctx)) {
        pushToast("Finish the current review first.");
        return;
      }
      const handle = runTransform(ctx, transform, range);
      runHandleRef.current = handle;
      setActiveRun({ label: transform.label, status: TransformRunStatus.streaming, text: "" });
      setCurrent(-1);
      handle.onText((text) =>
        setActiveRun((live) => (live === null ? live : { ...live, text })),
      );
      handle.done
        .then((outcome) => {
          if (outcome === TransformOutcome.review) {
            const before = ctx.get(editorViewCtx).state.doc;
            const proposed = handle.proposed();
            preReviewDoc.current = before;
            setDetached(proposed ? detachedComments(inlineAnchorsRef.current, before, proposed) : []);
            setResolveDetached(true);
            setNotes(handle.notes());
            setActiveRun((live) =>
              live === null ? live : { ...live, status: TransformRunStatus.reviewing },
            );
            return;
          }
          // Stopped, or a result with nothing in it — either way there is no
          // review to hand over, and the panel should not sit there implying one.
          setActiveRun(null);
          if (outcome === TransformOutcome.empty) {
            pushToast(transform.emptyMessage ?? "No changes were suggested.");
          }
        })
        .catch((error) => {
          setActiveRun(null);
          pushToast(errorMessage(error));
        })
        .finally(() => {
          runHandleRef.current = null;
        });
    });
  };
  // What contributions drive: stable per busy state, so a contribution's
  // effects do not re-run on every keystroke.
  const dispatchRef = useRef(dispatchTransform);
  dispatchRef.current = dispatchTransform;
  const busy = activeRun !== null;
  const editorHandle = useMemo<EditorHandle>(
    () => ({ busy, transform: (transform, range) => dispatchRef.current(transform, range) }),
    [busy],
  );

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

  // The review ending closes the panel, including when the last pair was accepted by hand.
  // Any count change rebuilds every decoration, so the marked "current" element is stale.
  useEffect(() => {
    setCurrent(-1);
    rootRef.current
      ?.querySelectorAll<HTMLElement>(DIFF_CONTROLS_SELECTOR)
      .forEach((node) => node.removeAttribute("data-current"));
    if (!review.active) {
      setActiveRun((live) => (live?.status === TransformRunStatus.reviewing ? null : live));
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
      setNotes([]);
    }
  }, [review.active, review.changes]);

  const users = useQuery({ ...usersQuery, enabled: mention?.type === "@" });
  const issues = useQuery({
    ...searchQuery(mention?.query ?? "", MENTION_LIMIT),
    enabled: mention?.type === "#" && Boolean(mention?.query),
  });
  // RADD-1327: `#` also names any other MENTIONABLE registered type (a plugin's
  // entity), each hit filtered by its owner's read gate. The token is
  // `#[Title](<the entity's own url>)`, which the reader renders as a chip.
  const entities = useQuery({
    ...entitySearchQuery(mention?.query ?? "", { exclude: "item", mentionable: true, limit: MENTION_LIMIT }),
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
      const issueHits = (issues.data?.results ?? []).map((hit) => ({ label: hit.key, href: hit.key, sub: hit.title }));
      const entityHits = (entities.data?.groups ?? []).flatMap((group) =>
        group.hits.filter((hit) => hit.url).map((hit) => ({ label: hit.title, href: hit.url, sub: group.label })),
      );
      return [...issueHits, ...entityHits].slice(0, MENTION_LIMIT);
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
  }, [mention, users.data, issues.data, entities.data, quickActions]);

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
    const extensionsOn = extensionsRef.current;
    const bindingOn = bindingRef.current;
    // A recreate (a switch back from plain mode) binds again; typing is
    // refused until it has — the window is a few milliseconds, but a
    // keystroke in it would land in a document about to be replaced.
    if (bindingOn) boundRef.current = false;
    let sourceTimer: ReturnType<typeof setTimeout> | undefined;
    const publish = (markdown: string) => {
      contentRef.current = markdown;
      onChangeRef.current(markdown);
      // Only surfaces with extensions publish the live markdown, debounced (a toc per keystroke is wasted work).
      if (extensionsOn) {
        clearTimeout(sourceTimer);
        sourceTimer = setTimeout(() => onSourceChangeRef.current(markdown), SOURCE_DEBOUNCE_MS);
      }
    };
    const editor = makeEditor({
      root,
      value: contentRef.current,
      editable: bindingOn ? () => boundRef.current : true,
      // A bound document's undo is the binding's (RADD-1397): Mod-z must undo
      // YOUR edits to a shared copy, and the history plugin's keymap,
      // registered first, would otherwise win the key and undo everyone's.
      history: !bindingOn,
      // Bound, the change plugin below is the one publisher: Milkdown's
      // listener serialises the doc of the last LOCAL transaction, 200 ms
      // later — after a colleague's change that arrived meanwhile, that is a
      // stale copy, and it overwrote the fresh one the saver was about to write.
      onMarkdown: bindingOn ? undefined : publish,
    });
    // @/#/"/" triggers (before create) — not on anonymous pages: the popups
    // query the user directory / issue search, both logged-in surfaces.
    if (!anonymous) editor.use(mentionProsePlugin(store));
    // Same chip rendering as the read-mode viewer (clicks consumed while editing).
    editor.use(mentionChipsPlugin({ readonly: false, openIssue: () => {} }));
    // Feeds the toolbar's active state (RADD-749). A plugin view, so the snapshot
    // is recomputed from the editor's own updates rather than polled.
    editor.use(toolbarStatePlugin(setSnapshot));
    // Bound, every change is published from the CURRENT document — the
    // binding's too, which Milkdown's listener skips (they are applied outside
    // the history). Debounced: a burst of keystrokes serialises once.
    let boundSerializeTimer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    if (bindingOn) {
      editor.use($prose(() => documentChangePlugin(() => {
        clearTimeout(boundSerializeTimer);
        boundSerializeTimer = setTimeout(() => {
          if (!disposed) publish(editor.action(getMarkdown()));
        }, BOUND_SERIALIZE_MS);
      })));
    }
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
    // Aborted when this instance goes before its binding has bound.
    const bindAbort = new AbortController();
    let unbind: (() => void) | undefined;
    const created = (async () => {
      // The review machinery, on every instance (inert until a review opens), so a contribution
      // arriving or leaving mid-edit needs no recreate. `diffComponent` is registered only for the
      // ctx slice our fork reads (labels + customBlockTypes) — without it create raises "Context
      // not found" — then its decoration plugin is swapped for ours.
      editor.use(diff).use(diffComponent);
      await editor.remove(diffDecorationPlugin);
      editor
        .use(raddDiffDecoration)
        .use(reviewStatePlugin(setReview))
        .use(
          selectionRectPlugin((rect) => {
            if (offersSelectionRef.current) setSelectionRect(rect);
          }),
        );
      await editor.create();
      if (bindingOn) {
        // RADD-1397: the binding makes the document a copy that lives
        // elsewhere — it seeds, syncs and adds its plugins; the editor only
        // waits, then accepts typing. `contentRef` is the CURRENT markdown
        // (Jira markup converted), the text the local copy has been showing.
        const off = await bindUntilAborted(bindingOn, bindableEditor(editor, contentRef.current), bindAbort.signal);
        if (disposed || !off) return;
        unbind = off;
        boundRef.current = true;
        // Re-ask `editable`: ProseMirror reads it when the state is updated.
        editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          view.updateState(view.state);
        });
      }
      if (autoFocus) root.querySelector<HTMLElement>(".ProseMirror")?.focus();
      // Read-mode transform hand-off: run once, on the first instance created.
      const handedOff = initialTransformRef.current;
      if (handedOff && !disposed) {
        initialTransformRef.current = null;
        dispatchRef.current(handedOff);
      }
    })();
    return () => {
      clearTimeout(sourceTimer);
      clearTimeout(boundSerializeTimer);
      disposed = true;
      bindAbort.abort();
      // Destroy only after create resolves, so an unmount mid-init can't race.
      // Unbind first: what the binding is bound to outlives this editor for a
      // moment (its owner closes it after a last save), and a change landing
      // on a destroyed context throws.
      void created.then(() => {
        try {
          unbind?.();
        } catch {
          // Already torn down — nothing left to unbind.
        }
        editor.destroy();
      });
      if (editorRef.current === editor) editorRef.current = null;
      // A run belongs to the instance it started on.
      runHandleRef.current?.cancel();
    };
    // Recreated on mode switch only — `value` changes are ignored (remount to
    // reseed).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plain]);

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
            {/* Toolbar + run band travel together, so both stay reachable in a
                long document. The wrapper carries the stickiness: the toolbar's
                own `sticky top-0` then has no room to move inside it, which is
                what keeps the two from sliding over each other. */}
            <div className="sticky top-0 z-[5]">
              {/* Ours (RADD-749). Outside the editor root: ProseMirror owns that
                  node's DOM, so React children inside it would be fought over. */}
              <EditorToolbar
                snapshot={snapshot}
                onAction={onToolbarAction}
                onInsertSymbol={(text) => editorRef.current?.action((ctx) => {
                  const view = ctx.get(editorViewCtx);
                  view.dispatch(view.state.tr.insertText(text).scrollIntoView());
                  view.focus();
                })}
                onHeading={onHeading}
                images={Boolean(onUploadImage)}
                tables
                extra={
                  <>
                    {/* Contributed buttons (RADD-1395), before the host's own. */}
                    {offersActions && <Slot id={SlotId.editorToolbarAction} editor={editorHandle} />}
                    {extensions && (
                      <ToolbarExtraButton
                        icon={<Blocks size={16} className="radd-extension-toolbar-icon" aria-hidden />}
                        title="Insert extension"
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
              {activeRun && (
                <TransformRunPanel
                  run={activeRun}
                  changes={review.changes}
                  current={current}
                  onNavigate={navigateReview}
                  onStop={() => runHandleRef.current?.cancel()}
                  onAcceptAll={() => run(acceptAllDiffsCmd.key)}
                  onRejectAll={() => run(clearDiffReviewCmd.key)}
                  detached={detached.length}
                  resolveDetached={resolveDetached}
                  onResolveDetachedChange={setResolveDetached}
                  notes={notes}
                />
              )}
            </div>
            {/* ProseMirror owns this node's DOM — keep it free of React children (popup is portaled). */}
            <div ref={rootRef} />
          </>
        )}
        {/* GitLab-style mode bar: same markdown either way, pick your editing surface. */}
        <div className="flex items-center justify-between border-t border-subtle px-2.5 py-1">
          {binding ? (
            // A textarea cannot bind: the plain mode is not offered to a
            // bound document rather than offered and refused.
            <span className="text-[11px] text-fg-muted">{binding.label}</span>
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
      {!plain && offersSelectionActions && <SelectionActions rect={selectionRect} editor={editorHandle} />}
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
