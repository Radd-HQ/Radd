export const CommentVisibility = {
  public: "public",
  internal: "internal",
} as const;
export type CommentVisibilityValue = (typeof CommentVisibility)[keyof typeof CommentVisibility];
export const COMMENT_VISIBILITY_LABELS: Record<CommentVisibilityValue, string> = {public: "Public", internal: "Internal"};
