/** Comments (spec 02). */
import type { UserRef } from "./items";
// ---------------------------------------------------------------------------
// Comments (spec 02 — module may 404 until the backend wave lands)
// ---------------------------------------------------------------------------

/** Internal comments are gated by `comment.read_internal` (spec 07). */
export const CommentVisibility = {
  public: "public",
  internal: "internal",
} as const;
export type CommentVisibilityValue = (typeof CommentVisibility)[keyof typeof CommentVisibility];

/** Where an inline comment points (RADD-726) — a text-quote selector, not an
 *  offset. See `lib/anchoring.ts` for why. */
export interface CommentAnchor {
  quote: string;
  prefix?: string;
  suffix?: string;
}

export interface Comment {
  id: string;
  /** RADD-717: what this hangs off — "item" or "page". */
  entity_type: string;
  entity_id: string;
  author: UserRef | null;
  body: string;
  is_thread?: boolean;
  visibility: CommentVisibilityValue;
  /** Spec 50: team ids an internal comment is narrowed to (empty = all readers). */
  visible_to_teams: string[];
  created_at: string;
  updated_at: string;
  /** RADD-726. Null = a general comment or discussion. */
  anchor: CommentAnchor | null;
  resolved_at: string | null;
  resolved_by: string | null;
  /** Who resolved the thread, for "Resolved by …". */
  resolver_name?: string | null;
  /** RADD-1283: whether THIS reader may resolve/unresolve it, under the parent's rule. */
  can_resolve?: boolean;
  parent_comment_id?: string | null;
  reply_count?: number;
}

/** The authenticated actor is the author; `internal` needs comment.read_internal. */
export interface CommentCreate {
  body: string;
  is_thread?: boolean;
  visibility?: CommentVisibilityValue;
  /** Spec 50: narrow an internal comment to these team ids (empty = all readers). */
  visible_to_teams?: string[];
}

/** RADD-1283: who may resolve or unresolve a thread. Managers always may, except
 *  that `managers` is only them. A wire format — the server's `ThreadResolvers`. */
export const ThreadResolvers = {
  author: "author",
  assignee: "assignee",
  anyone: "anyone",
  managers: "managers",
} as const;
export type ThreadResolversValue = (typeof ThreadResolvers)[keyof typeof ThreadResolvers];

export interface ThreadResolutionPolicy {
  default: ThreadResolversValue;
  overrides: { issue_type_id: string; resolvers: ThreadResolversValue }[];
}
