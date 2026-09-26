import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useContributionOwner } from "./slots";

/**
 * The rich editor's extension points (RADD-1395).
 *
 * The editor — Milkdown, ProseMirror, the toolbar, the per-block diff review, code blocks and
 * `radd:*` nodes — is HOST code that issues, comments and the wiki share. A plugin extends it
 * through three slots and one mechanism, none of which names a feature:
 *
 *   - `editor.toolbar.action` — a toolbar button (`EditorToolbarActionProps`);
 *   - `editor.selection.action` — chrome over a text selection (`EditorSelectionActionProps`);
 *   - `content.read.action` — an action on RENDERED content (`ReadActionProps`);
 *   - a TRANSFORM — a contribution hands the editor a streamed replacement for the selection or
 *     the whole document (`EditorHandle.transform`, or `ReadActionProps.transform` to open the
 *     editor with one), and the editor shows its own reviewable diff with accept/reject.
 *
 * The review is the editor's; what the replacement IS — its prompt, its protocol, what it must
 * protect — is the contribution's. A reading surface may also offer a panel beside the text
 * (`useReadingPane`), where an answer has room to be read.
 */

/** A range of the document, in editor positions. */
export interface EditorRange {
  from: number;
  to: number;
}

/** A non-empty selection in a focused editor, and where it sits on screen. */
export interface EditorSelection extends EditorRange {
  left: number;
  top: number;
  bottom: number;
}

/** What a transform reads, as markdown. */
export interface EditorTransformInput {
  /** The whole document. */
  document: string;
  /** The part the replacement takes the place of; "" when the run covers the whole document. */
  selection: string;
}

export interface EditorTransformResult {
  /** The replacement for `selection` (or for the whole document), as markdown. */
  replacement: string;
  /** Lines the review shows beside the diff — what the transform had to do to the text. */
  notes?: string[];
}

/**
 * A streamed replacement the editor turns into a reviewable diff.
 *
 * `run` produces the replacement; `onText` reports it as it grows (the whole replacement so far,
 * not a chunk), and the editor previews it. Resolve `null` when the run was withdrawn — nothing to
 * review, nothing to report. Reject with a presentable error: its message is what the person sees.
 * The editor aborts `signal` when the person presses Stop.
 */
export interface EditorTransform {
  /** What the run is called while it streams and under review — an action's name, a prompt. */
  label: string;
  /** Said when the run ends with nothing to change. */
  emptyMessage?: string;
  run: (
    input: EditorTransformInput,
    progress: { signal: AbortSignal; onText: (text: string) => void },
  ) => Promise<EditorTransformResult | null>;
}

/** The live editor, as its contributions see it. */
export interface EditorHandle {
  /** A transform is streaming or its review is open; the editor refuses a second one. */
  busy: boolean;
  /** Stream `transform` over `range` — captured by chrome that moved focus — or over the live
   *  selection, which is the whole document when it is empty. */
  transform: (transform: EditorTransform, range?: EditorRange) => void;
}

/** `editor.toolbar.action` props. */
export interface EditorToolbarActionProps {
  editor: EditorHandle;
}

/** `editor.selection.action` props. */
export interface EditorSelectionActionProps {
  editor: EditorHandle;
  /** The live selection, or null while nothing is selected or the editor is not focused. */
  selection: EditorSelection | null;
}

/** What rendered content belongs to: the entity it is (a comment, a page, an issue — whose
 *  content is its description), and the entity that holds it. */
export interface ContentContext {
  entityType: string;
  entityId: string;
  parent?: { entityType: string; entityId: string };
}

/** `content.read.action` props. */
export interface ReadActionProps {
  /** The content's markdown. */
  text: string;
  context: ContentContext;
  /** Present only when the reader may rewrite the content: opens its editor running the transform. */
  transform?: (transform: EditorTransform) => void;
  /** What the content is, for accessible names: "the description", "this comment". */
  subject: string;
  /** The host's placement for the trigger (a reveal on hover). */
  className?: string;
}

/** `item.draft.assist` props: an issue being written. */
export interface ItemDraftAssistProps {
  title: string;
  description: string;
  projectId: string;
  /** Issue keys another section already shows — do not suggest them twice. */
  exclude: string[];
}

/** A panel beside the text being read (`useReadingPane`). */
export interface ReadingPanel {
  /** The panel's heading. */
  title: string;
  /** Its accessible name, when it should say more than the title. */
  label?: string;
  icon?: ReactNode;
  /** The body. Each open renders it afresh, so opening the same panel again runs it again. */
  render: () => ReactNode;
}

type OpenPanel = (panel: ReadingPanel, owner: string | null) => void;

/** Provided by a reading surface that has room beside its text (the issue page, a wiki page). */
export const ReadingPaneContext = createContext<OpenPanel | null>(null);

/**
 * Open a panel beside the text being read — or null where the surface has none, so the caller
 * answers in place. A panel opened from a plugin's contribution closes when that plugin is
 * withdrawn.
 */
export function useReadingPane(): ((panel: ReadingPanel) => void) | null {
  const open = useContext(ReadingPaneContext);
  const owner = useContributionOwner();
  return useMemo(() => (open ? (panel: ReadingPanel) => open(panel, owner) : null), [open, owner]);
}
