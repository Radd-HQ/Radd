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

export interface Comment {
  id: string;
  item_id: string;
  author: UserRef;
  body: string;
  visibility: CommentVisibilityValue;
  /** Spec 50: team ids an internal comment is narrowed to (empty = all readers). */
  visible_to_teams: string[];
  created_at: string;
  updated_at: string;
}

/** The authenticated actor is the author; `internal` needs comment.read_internal. */
export interface CommentCreate {
  body: string;
  visibility?: CommentVisibilityValue;
  /** Spec 50: narrow an internal comment to these team ids (empty = all readers). */
  visible_to_teams?: string[];
}
