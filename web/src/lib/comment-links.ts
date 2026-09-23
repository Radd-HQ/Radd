import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { api } from "./api";
import { On401 } from "./constants";
import { apiCommentPath } from "./constants";

/**
 * RADD-1297 — links to one comment.
 *
 * The address is `?comment=<id>` beside whatever the page already carries: the
 * issue page (`/issues/TD-1?comment=…`), the issue peek (`?peek=TD-1&comment=…`)
 * or a wiki page (`/pages/…?comment=…`, the permalink forwards it). A query
 * parameter, not a hash, so it survives the router and the short-link fallback.
 */
export interface CommentLocation {
  id: string;
  /** The thread to open: the comment itself, or a reply's parent. */
  root_id: string;
  entity_type: string;
  entity_id: string;
  /** An inline annotation (the page rail) rather than a discussion comment. */
  anchored: boolean;
}

export const COMMENT_PARAM = "comment";

/** The linked comment's id from the address, if any. */
export function useLinkedCommentId(): string | undefined {
  return useRouterState({
    select: (state) => {
      const value = (state.location.search as Record<string, unknown>)[COMMENT_PARAM];
      return typeof value === "string" && value ? value : undefined;
    },
  });
}

/**
 * Where the linked comment lives — but only when it belongs to `entityId`.
 * Two threads can be on screen (an issue under a peek); each acts only on its
 * own comments. A comment the reader cannot see resolves to nothing: the
 * server answers 404 exactly as for one that does not exist, and the page just
 * opens as it would have.
 */
export function useLinkedComment(entityId: string): CommentLocation | null {
  const id = useLinkedCommentId();
  const located = useQuery({
    queryKey: ["commentLocate", id],
    queryFn: ({ signal }) =>
      api.get<CommentLocation>(`${apiCommentPath(id!)}/locate`, { signal, on401: On401.throw }),
    enabled: Boolean(id),
    retry: false,
    staleTime: Infinity,
  });
  return located.data && located.data.entity_id === entityId ? located.data : null;
}

/**
 * Scroll the linked comment into view and highlight it, once it is rendered.
 * Rows are found by `data-comment-id` — every comment surface already sets it.
 * Returns true once landed, so a caller can stop widening/expanding.
 */
export function useLandOnComment(target: string | null | undefined): boolean {
  const [landed, setLanded] = useState<string | null>(null);
  useEffect(() => {
    if (!target || landed === target) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      const row = document.querySelector<HTMLElement>(`[data-comment-id="${CSS.escape(target)}"]`);
      if (row) {
        window.clearInterval(timer);
        row.scrollIntoView({ block: "center" });
        row.setAttribute("data-comment-linked", "");
        window.setTimeout(() => row.removeAttribute("data-comment-linked"), 4000);
        setLanded(target);
      } else if (++tries > 40) {
        window.clearInterval(timer); // ~10s: it is not coming (deleted meanwhile)
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [target, landed]);
  return landed === target;
}

/** The canonical link to an issue comment — the issue page, whatever surface
 *  (a peek over another page) it was copied from. */
export function issueCommentHref(itemKey: string, commentId: string): string {
  return `${window.location.origin}/issues/${encodeURIComponent(itemKey)}?${COMMENT_PARAM}=${commentId}`;
}

/** The absolute link to one comment on the page being viewed now. */
export function commentHref(commentId: string): string {
  const url = new URL(window.location.href);
  url.searchParams.set(COMMENT_PARAM, commentId);
  return url.toString();
}
