import { infiniteQueryOptions, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { apiCommentPath } from "../../lib/constants";
import { Entity, entityMeta, invalidateEntities } from "../../lib/cache";
import { chronologicalComments, type CommentPage } from "../../lib/queries/comment-feed";
import { relativeTime } from "../../lib/dates";
import type { Comment } from "../../lib/types";
import { LazyRichViewer } from "../editor/LazyRichViewer";
import { Button } from "../Button";
import { CommentHistory } from "../CommentHistory";

export function PageCommentReplies({row, canReply, draft, onDraft}: {
  row: Comment; canReply: boolean; draft: string; onDraft: (value: string) => void;
}) {
  const client = useQueryClient();
  const query = useInfiniteQuery(infiniteQueryOptions({
    queryKey: ["commentReplies", row.id], meta: entityMeta(Entity.comment),
    initialPageParam: null as string | null,
    queryFn: ({pageParam, signal}) => api.get<CommentPage>(`${apiCommentPath(row.id)}/replies`, {
      signal, query: {limit: "50", ...(pageParam ? {before: pageParam} : {})},
    }),
    getNextPageParam: page => page.older_cursor ?? undefined,
    retry: false,
  }));
  const post = useMutation({
    mutationFn: (body: string) => api.post<Comment>(`${apiCommentPath(row.id)}/replies`, {body}),
    onSuccess: () => { onDraft(""); },
    onSettled: () => void invalidateEntities(client, Entity.comment),
  });
  return <div className="mt-3 space-y-3 border-t border-subtle pt-3" data-comment-replies={row.id}>
    <CommentHistory hasOlder={query.hasNextPage} loading={query.isFetchingNextPage}
      onOlder={() => query.fetchNextPage()} error={query.isError ? errorMessage(query.error) : undefined}>
      {query.isPending && <p role="status" className="text-xs text-fg-muted">Loading replies…</p>}
      {query.isError && <Button size="sm" variant="ghost" onClick={() => void query.refetch()}>Retry replies</Button>}
      {chronologicalComments(query.data?.pages).map(reply => <div key={reply.id} data-comment-id={reply.id}
        className="border-l-2 border-subtle pl-2">
        <p className="text-xs"><span className="font-medium text-heading">{reply.author?.name ?? "Unknown author"}</span>{" "}
          <span className="text-fg-faint" title={reply.created_at}>{relativeTime(reply.created_at)}</span></p>
        <LazyRichViewer text={reply.body} />
      </div>)}
    </CommentHistory>
    {canReply && (row.resolved_at ? <p className="text-xs text-fg-muted">Reopen this thread to reply.</p> :
      <form onSubmit={event => {event.preventDefault(); if (draft.trim() && !post.isPending) post.mutate(draft);}}>
        <textarea aria-label="Reply to inline comment" placeholder="Write a reply…" rows={3} value={draft}
          disabled={post.isPending} onChange={event => onDraft(event.target.value)}
          className="w-full resize-y rounded-md border border-subtle bg-base p-2 text-sm text-fg focus:outline-2 focus:outline-focus" />
        {post.isError && <p role="alert" className="my-1 text-xs text-status-danger-ink">{errorMessage(post.error)}</p>}
        <Button type="submit" size="sm" disabled={!draft.trim() || post.isPending}>{post.isPending ? "Replying…" : "Reply"}</Button>
      </form>)}
  </div>;
}
