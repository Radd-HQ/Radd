import { infiniteQueryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import type { Comment } from "../types";

export const CommentSection = { all: "all", discussion: "discussion", inline: "inline" } as const;
export type CommentSectionValue = typeof CommentSection[keyof typeof CommentSection];
export interface CommentPage { comments: Comment[]; older_cursor: string | null }

/** The latest window first; older pages prepend visually without offset drift. */
export function commentFeedQuery(key: readonly unknown[], path: string, section: CommentSectionValue) {
  return infiniteQueryOptions({
    queryKey: [...key, "feed", { section }],
    meta: entityMeta(Entity.comment),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => api.get<CommentPage>(`${path}/feed`, {
      signal, query: { section, limit: "50", ...(pageParam ? { before: pageParam } : {}) },
    }),
    getNextPageParam: (page) => page.older_cursor ?? undefined,
    retry: false,
  });
}

export function chronologicalComments(pages: CommentPage[] | undefined): Comment[] {
  return [...(pages ?? [])].reverse().flatMap(page => page.comments);
}
