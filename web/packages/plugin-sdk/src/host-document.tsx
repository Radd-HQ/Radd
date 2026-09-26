import type { ComponentType, ReactNode } from "react";
import type { TextAnchor } from "./anchoring";
import { providedNow, useProvided } from "./host-registry";
import { TextArea, type AvatarUser } from "./primitives";

/**
 * The host's document surfaces, bridged (RADD-1392).
 *
 * The rich editor, its viewer, the read-mode markdown renderer, the AI read menu and live
 * co-editing are HOST code: issues and comments use them too, and Milkdown + ProseMirror +
 * CodeMirror are far too heavy to bundle into a plugin. The host provides them at startup; a
 * plugin renders them through the wrappers below with the typed contracts declared here. The
 * contracts carry no editor internals — a live room is an opaque handle a plugin passes back.
 */

/** A reader ticked a checklist box: its index among the task items in document order. */
export interface TaskToggle {
  index: number;
  checked: boolean;
}

/** An AI transform to run over the whole document once an editor is ready (the read-mode AI
 *  menu's hand-off to edit mode). */
export interface AiRun {
  instruction: string;
  label: string;
}

/** An open inline comment anchored in the document, so an AI review can count what it strands. */
export interface InlineAnchorRef {
  id: string;
  anchor: TextAnchor;
}

/** A live co-editing room (spec 122), opaque to plugins: hand it back to `RichEditor`'s `live`.
 *  `session` keys the editor — a new room needs a new editor instance. */
export interface LiveRoom {
  readonly session: string;
}

export interface RichEditorProps {
  /** The seed markdown; the editor is uncontrolled after mount (remount with a `key` to reseed). */
  value: string;
  onChange: (markdown: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  className?: string;
  /** Offer the `radd:*` extension picker in the toolbar (page bodies). */
  extensions?: boolean;
  /** The attachment parent pasted and inserted images are stored on. Omit to disable images. */
  attachTo?: { entityType: string; entityId: string };
  initialAiRun?: AiRun;
  inlineAnchors?: InlineAnchorRef[];
  /** A review ended with those passages gone and the person chose to resolve their comments. */
  onDetachedComments?: (ids: string[]) => void;
  /** Bind the document to a live room instead of the local copy; `value` is the seed template. */
  live?: LiveRoom;
}

export interface RichViewerProps {
  text: string;
  className?: string;
  /** Mount at once instead of when scrolled near — for surfaces that read the rendered output. */
  eager?: boolean;
  /** Fires once the rendered document is in the DOM. */
  onReady?: () => void;
  /** Present only when the reader may write this text. */
  onToggleTask?: (toggle: TaskToggle) => Promise<unknown>;
  /** The element task indexes count across, when this viewer is one segment of a document. */
  taskScope?: () => HTMLElement | null;
}

export interface MarkdownProps {
  text: string;
}

export interface AiReadMenuProps {
  /** The markdown this menu operates on. */
  text: string;
  /** Find similar issues from a text seed. */
  similar?: { seedKey: string; excludeItemId?: string };
  /** The entity whose image attachments Summarize may show a vision model. */
  imagesOf?: { entity_type: string; entity_id: string };
  /** Present when the actor may rewrite the text: a transform opens the editor with the run. */
  onTransform?: (run: AiRun) => void;
  /** Accessible name for the trigger button. */
  label: string;
  className?: string;
}

/** Where AI answers open: a results pane beside `children` instead of the menu's popover. */
export interface AiResultsPaneProps {
  children: ReactNode;
}

export const LiveRole = { editor: "editor", observer: "observer" } as const;
export type LiveRoleValue = (typeof LiveRole)[keyof typeof LiveRole];

/** One person in a live room; several tabs of one account fold into one entry. */
export interface LivePerson {
  user: { id: string; name: string; color: string; emoji: string | null };
  role: LiveRoleValue;
  clientIds: number[];
  self: boolean;
}

export interface LiveSession {
  room: LiveRoom | null;
  joining: boolean;
  /** The room refused this client (or cannot exist): run the single-editor flow. */
  failed: boolean;
  presence: { people: LivePerson[]; saver: number | null };
  isSaver: boolean;
  /** The final save, when this client is the elected saver. */
  finish: () => Promise<void>;
}

export interface LiveSessionOptions {
  pageId: string;
  /** null = stay out (a visitor); observer = presence only; editor = the live document. */
  role: LiveRoleValue | null;
  user: { id: string; name: string; avatar_color?: string | null; avatar_emoji?: string | null } | null;
  /** The editor's live markdown — read at save time, never a captured value. */
  getMarkdown: () => string;
  onSaved?: (saved: { version: number }) => void;
  onSaveError?: (error: unknown) => void;
}

export interface EditingNowProps {
  people: LivePerson[];
  /** The people directory, for real avatars. */
  users?: AvatarUser[];
  className?: string;
}

/** What the host provides for documents. */
export interface DocumentHost {
  RichEditor?: ComponentType<RichEditorProps>;
  RichViewer?: ComponentType<RichViewerProps>;
  Markdown?: ComponentType<MarkdownProps>;
  AiReadMenu?: ComponentType<AiReadMenuProps>;
  AiResultsPane?: ComponentType<AiResultsPaneProps>;
  EditingNow?: ComponentType<EditingNowProps>;
  /** A hook: provided once at startup, so every render calls the same function. */
  useLiveSession?: (options: LiveSessionOptions) => LiveSession;
}

const plain = "whitespace-pre-wrap text-[13px] leading-relaxed text-fg";

/** The host's rich markdown editor, else a plain text area. */
export function RichEditor(props: RichEditorProps) {
  const { RichEditor: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return <TextArea aria-label={props.placeholder ?? "Text"} placeholder={props.placeholder}
    defaultValue={props.value} onChange={(event) => props.onChange(event.target.value)} />;
}

/** The host's rendered-markdown viewer, else the raw text. */
export function RichViewer(props: RichViewerProps) {
  const { RichViewer: Host } = useProvided();
  return Host ? <Host {...props} /> : <div className={plain}>{props.text}</div>;
}

/** The host's read-mode markdown renderer (mentions, issue chips, `radd:*` blocks), else raw text. */
export function Markdown(props: MarkdownProps) {
  const { Markdown: Host } = useProvided();
  return Host ? <Host {...props} /> : <div className={plain}>{props.text}</div>;
}

/** The read-mode AI menu. Renders nothing without a host (or when no AI gate lets anything through). */
export function AiReadMenu(props: AiReadMenuProps) {
  const { AiReadMenu: Host } = useProvided();
  return Host ? <Host {...props} /> : null;
}

/** An AI results pane beside the content; without a host, just the content. */
export function AiResultsPane(props: AiResultsPaneProps) {
  const { AiResultsPane: Host } = useProvided();
  return Host ? <Host {...props} /> : <>{props.children}</>;
}

/** Who else is in the live room. */
export function EditingNow(props: EditingNowProps) {
  const { EditingNow: Host } = useProvided();
  return Host ? <Host {...props} /> : null;
}

const NO_LIVE_SESSION: LiveSession = {
  room: null,
  joining: false,
  failed: true,
  presence: { people: [], saver: null },
  isSaver: false,
  finish: async () => undefined,
};

function noLiveSession(): LiveSession {
  return NO_LIVE_SESSION;
}

/** Join a page's live room (spec 122). Without a host the session has `failed`, so the caller
 *  runs its single-editor flow. The host provides the hook before the first render. */
export function useLiveSession(options: LiveSessionOptions): LiveSession {
  const provided = providedNow().useLiveSession ?? noLiveSession;
  return provided(options);
}
