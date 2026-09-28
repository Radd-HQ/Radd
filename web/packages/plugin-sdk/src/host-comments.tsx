import type { ComponentType, ReactNode } from "react";
import type { TextAnchor } from "./anchoring";
import { bridged } from "./bridge";
import { providedNow } from "./host-registry";
import type { TaskToggle } from "./host-document";

/** The host's comment kit (feed, threads, replies, resolution, links), bridged for plugins that show a
 *  discussion on their own entity. Hooks are provided once at startup, so every render calls the same function. */

/** A text-quote selector: where an inline comment points. */
export type CommentAnchor = TextAnchor;

/** A comment as the comments API serves it — the fields a plugin surface reads. */
export interface CommentRow {
  id: string;
  entity_type: string;
  entity_id: string;
  author: { id: string; name: string; avatar_color?: string | null; avatar_emoji?: string | null } | null;
  body: string;
  created_at: string;
  updated_at: string;
  anchor: CommentAnchor | null;
  is_thread?: boolean;
  resolved_at: string | null;
  resolver_name?: string | null;
  /** Whether THIS reader may resolve or unresolve it, under the parent's rule. */
  can_resolve?: boolean;
  parent_comment_id?: string | null;
  reply_count?: number;
}

export const CommentSection = { all: "all", discussion: "discussion", inline: "inline" } as const;
export type CommentSectionValue = (typeof CommentSection)[keyof typeof CommentSection];

export interface CommentFeedOptions {
  /** The comment parent's registered entity type ("page", "item", …). */
  parentType: string;
  parentId: string;
  section: CommentSectionValue;
  /** Only still-open resolvable threads. */
  unresolvedOnly?: boolean;
  /** A linked comment: the first window widens to include it. */
  through?: string;
  enabled?: boolean;
}

/** The latest window first; older windows load on request. `comments` is chronological. */
export interface CommentFeed {
  comments: CommentRow[];
  hasOlder: boolean;
  loadingOlder: boolean;
  loadOlder: () => unknown;
  isPending: boolean;
  isError: boolean;
  error: unknown;
}

/** Where a linked comment (`?comment=<id>`) lives. */
export interface CommentLocation {
  id: string;
  /** The thread to open: the comment itself, or a reply's parent. */
  root_id: string;
  entity_type: string;
  entity_id: string;
  /** An inline annotation rather than a discussion comment. */
  anchored: boolean;
}

/** Which comments show their replies. Open by default, except a resolved thread; a reader's own
 *  choice survives refreshes until the thread's resolution changes. */
export interface ThreadExpansion {
  isOpen: (row: CommentRow) => boolean;
  toggle: (row: CommentRow) => void;
}

export interface CommentRepliesProps {
  row: CommentRow;
  canReply: boolean;
  /** The unsent reply; a composer that mounts with one opens on it. */
  draft: string;
  onDraft: (value: string) => void;
  canResolve: boolean;
  /** RADD-1477: may edit and delete ANYONE's reply (a project manager); an author always may their own. */
  canManage?: boolean;
  linkedReplyId?: string;
  linkFor?: (commentId: string) => string;
  /**
   * RADD-1448 — the comment's whole thread footer. Given, mount this under EVERY comment: it draws
   * the "Hide 3 replies" disclosure (only when there are replies), a Reply action (when `canReply`)
   * that opens the composer under the replies in one click, `actions` beside them, the replies
   * while open, and the reply composer while replying (Cancel or Escape closes it and keeps the
   * draft; posting closes and clears it). Omitted: the older block, which the caller mounts only
   * while its own toggle is open, with Reply at its foot.
   */
  expansion?: ThreadExpansion;
  /** Footer controls after Reply, e.g. `ResolveThreadButton`. Only with `expansion`. */
  actions?: ReactNode;
}

/** What the discussion composer posts: an ordinary comment, or a resolvable thread. */
export const CommentComposerMode = { comment: "comment", thread: "thread" } as const;
export type CommentComposerModeValue = (typeof CommentComposerMode)[keyof typeof CommentComposerMode];

/**
 * RADD-1448 — a discussion's composer. Closed (`mode` null) it is a row of two buttons, Comment and
 * Start thread; open, a Comment | Thread switch, `controls`, `children` (the editor, autofocused by
 * its caller), and ONE submit with a Cancel. Cancel and Escape call `onMode(null)` — keep the draft,
 * so reopening shows it; close and clear it once the post lands.
 */
export interface CommentComposerProps {
  mode: CommentComposerModeValue | null;
  /** Open from the row, switch mode, or close (null). */
  onMode: (mode: CommentComposerModeValue | null) => void;
  /** The submit's words for this mode and audience: "Comment", "Start internal thread"… */
  submitLabel: string;
  /** False while there is nothing to post. */
  canSubmit: boolean;
  pending?: boolean;
  error?: string;
  onSubmit: () => void;
  /** Beside the mode switch: an audience control, where the surface has one. */
  controls?: ReactNode;
  /** The editor, and anything that sits above it (a team audience, a canned-response picker). */
  children: ReactNode;
}

export interface CommentHistoryProps {
  children: ReactNode;
  hasOlder: boolean;
  loading: boolean;
  onOlder: () => unknown;
  error?: string;
}

/** What the host provides for comments. */
export interface CommentHost {
  CommentReplies?: ComponentType<CommentRepliesProps>;
  CommentComposer?: ComponentType<CommentComposerProps>;
  CommentHistory?: ComponentType<CommentHistoryProps>;
  CopyCommentLink?: ComponentType<{ href: string; className?: string }>;
  ThreadBadge?: ComponentType<{ comment: CommentRow }>;
  ThreadFilter?: ComponentType<{ unresolvedOnly: boolean; onChange: (value: boolean) => void }>;
  ResolveThreadButton?: ComponentType<{ comment: CommentRow }>;
  useCommentFeed?: (options: CommentFeedOptions) => CommentFeed;
  useLinkedComment?: (entityId: string) => CommentLocation | null;
  useLandOnComment?: (commentId: string | null | undefined) => boolean;
  useThreadExpansion?: (linkedRoot?: string) => ThreadExpansion;
  commentHref?: (commentId: string) => string;
  repliesLabel?: (row: CommentRow, expanded: boolean, canReply: boolean) => string;
  threadRuleClass?: (row: CommentRow) => string;
  sendTaskToggle?: (path: string, toggle: TaskToggle, expectedBody: string) => Promise<unknown>;
}

export const CommentReplies = bridged("CommentReplies", () => null);

export const CommentComposer = bridged("CommentComposer", () => null);

/** A comment list that keeps its place while older comments prepend. */
export const CommentHistory = bridged("CommentHistory", (props) =>
  <div>{props.error && <p role="alert">{props.error}</p>}{props.children}</div>);

export const CopyCommentLink = bridged("CopyCommentLink", () => null);

export const ThreadBadge = bridged("ThreadBadge", () => null);

export const ThreadFilter = bridged("ThreadFilter", () => null);

export const ResolveThreadButton = bridged("ResolveThreadButton", () => null);

const NO_FEED: CommentFeed = {
  comments: [], hasOlder: false, loadingOlder: false, loadOlder: () => undefined,
  isPending: false, isError: true, error: new Error("Comments are unavailable"),
};
const noFeed = (): CommentFeed => NO_FEED;
const noLinked = (): CommentLocation | null => null;
const noLanding = (): boolean => false;
const defaultThreads: ThreadExpansion = {
  isOpen: (row) => !(row.is_thread && row.resolved_at),
  toggle: () => undefined,
};
const noExpansion = (): ThreadExpansion => defaultThreads;

/** A parent's comments, one section, newest window first. */
export function useCommentFeed(options: CommentFeedOptions): CommentFeed {
  return (providedNow().useCommentFeed ?? noFeed)(options);
}

/** The comment the address links to (`?comment=<id>`), when it belongs to `entityId`. */
export function useLinkedComment(entityId: string): CommentLocation | null {
  return (providedNow().useLinkedComment ?? noLinked)(entityId);
}

/** Scroll the linked comment into view and mark it, once rendered. True once landed. */
export function useLandOnComment(commentId: string | null | undefined): boolean {
  return (providedNow().useLandOnComment ?? noLanding)(commentId);
}

/** Which comments show their replies: open unless a resolved thread; manual choices survive
 *  refreshes; a linked one opens. */
export function useThreadExpansion(linkedRoot?: string): ThreadExpansion {
  return (providedNow().useThreadExpansion ?? noExpansion)(linkedRoot);
}

/** The absolute link to one comment on the page being viewed now. */
export function commentHref(commentId: string): string {
  const host = providedNow().commentHref;
  if (host) return host(commentId);
  const url = new URL(window.location.href);
  url.searchParams.set("comment", commentId);
  return url.toString();
}

/**
 * The words of the disclosure that shows or hides a comment's replies: "Hide 3 replies", "Show 1
 * reply", "Show 3 replies · resolved". Only for a comment that HAS replies — Reply is a separate
 * action, never this toggle. `canReply` no longer changes the words; it stays for the signature.
 */
export function repliesLabel(row: CommentRow, expanded: boolean, canReply: boolean): string {
  const host = providedNow().repliesLabel;
  if (host) return host(row, expanded, canReply);
  const count = row.reply_count ?? 0;
  const noun = `${count} ${count === 1 ? "reply" : "replies"}`;
  if (expanded) return `Hide ${noun}`;
  return `Show ${noun}${row.is_thread && row.resolved_at ? " · resolved" : ""}`;
}

/** The rule that marks a thread card (a leading space, or "" for a plain comment). */
export function threadRuleClass(row: CommentRow): string {
  return providedNow().threadRuleClass?.(row) ?? "";
}

/** Send one checklist tick to a surface's `…/tasks` endpoint; a refusal is reported, not thrown. */
export function sendTaskToggle(path: string, toggle: TaskToggle, expectedBody: string): Promise<unknown> {
  const host = providedNow().sendTaskToggle;
  return host ? host(path, toggle, expectedBody) : Promise.resolve(null);
}
