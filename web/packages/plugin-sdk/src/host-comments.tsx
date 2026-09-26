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

export interface ThreadExpansion {
  isOpen: (row: CommentRow) => boolean;
  toggle: (row: CommentRow) => void;
}

export interface CommentRepliesProps {
  row: CommentRow;
  canReply: boolean;
  draft: string;
  onDraft: (value: string) => void;
  canResolve: boolean;
  linkedReplyId?: string;
  linkFor?: (commentId: string) => string;
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
const closedThreads: ThreadExpansion = { isOpen: () => false, toggle: () => undefined };
const noExpansion = (): ThreadExpansion => closedThreads;

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

/** Which threads show their replies: manual choices survive refreshes; a linked one opens. */
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

/** "3 replies" / "Reply" / "Hide replies" — the thread toggle's words. */
export function repliesLabel(row: CommentRow, expanded: boolean, canReply: boolean): string {
  const host = providedNow().repliesLabel;
  return host ? host(row, expanded, canReply) : expanded ? "Hide replies" : canReply ? "Reply" : "View thread";
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
