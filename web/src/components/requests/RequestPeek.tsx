import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Package, UserRound } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import { portalRequestDetailQuery, queryKeys } from "../../lib/queries";
import type { PortalRequestComment } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { PageBody } from "../pages/PageBody";
import { Spinner } from "../Spinner";

/**
 * A requester's view of one request (RADD-796).
 *
 * NOT the issue peek. That one resolves through `item.read`, which a requester
 * holds nowhere — which is exactly why My Requests rows used to do nothing when
 * clicked. This shows what the relationship entitles them to: where it has got
 * to, who holds it, what shipped it, and the PUBLIC conversation.
 *
 * The reply box is not a nicety. A requester who cannot answer a question asked
 * of them is stuck, and the thread then reads as if they went quiet.
 */
export function RequestPeek({
  requestKey,
  onClose,
}: {
  requestKey: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery(portalRequestDetailQuery(requestKey));
  const [reply, setReply] = useState("");

  const send = useMutation({
    mutationFn: () =>
      api.post(`${ApiPath.portalRequests}/${requestKey}/comments`, { body: reply }),
    onSuccess: async () => {
      setReply("");
      // Both the thread and the LIST change: replying clears the row's marker.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.portalRequest(requestKey) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.portalRequests }),
      ]);
    },
  });

  const request = detail.data;

  return (
    <Modal title={request ? request.title : requestKey} onClose={onClose} wide>
      {detail.isPending ? (
        <Spinner label="Loading…" />
      ) : detail.isError ? (
        <p className="text-sm text-red-400">{errorMessage(detail.error)}</p>
      ) : request ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-fg-secondary">
            <span className="rounded bg-elevated px-1.5 py-px font-mono text-fg-muted">
              {request.key}
            </span>
            <span className="rounded border border-strong px-1.5 py-px">
              {request.state || "—"}
            </span>
            <span className="flex items-center gap-1">
              <UserRound size={11} aria-hidden />
              {request.assignee ?? "Unassigned"}
            </span>
            {request.release && (
              <span className="flex items-center gap-1 rounded bg-elevated px-1.5 py-px">
                <Package size={10} aria-hidden />
                {request.release}
              </span>
            )}
            {request.team && (
              <span className="rounded bg-elevated px-1.5 py-px">Shared with {request.team}</span>
            )}
          </div>

          {request.description && (
            <div className="rounded-lg border border-subtle bg-surface px-3 py-2">
              <PageBody text={request.description} />
            </div>
          )}

          <section className="flex flex-col gap-2" aria-label="Conversation">
            <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
              <MessageSquare size={12} aria-hidden />
              Conversation
            </h3>
            {request.comments.length === 0 ? (
              <p className="text-xs text-fg-faint">
                Nothing yet. Add a note below if there's more to say.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {request.comments.map((comment) => (
                  <CommentBubble key={comment.id} comment={comment} />
                ))}
              </ul>
            )}
          </section>

          <div className="flex flex-col gap-2">
            <textarea
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={3}
              placeholder="Add a reply…"
              aria-label="Reply to this request"
              className="w-full rounded-md border border-subtle bg-base px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus-visible:outline-2 focus-visible:outline-focus"
            />
            {send.isError && <p className="text-xs text-red-400">{errorMessage(send.error)}</p>}
            <div className="flex justify-end">
              <Button
                onClick={() => send.mutate()}
                disabled={!reply.trim() || send.isPending}
              >
                {send.isPending ? "Sending…" : "Reply"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

function CommentBubble({ comment }: { comment: PortalRequestComment }) {
  return (
    <li
      className={
        "rounded-lg border px-3 py-2 " +
        (comment.author_is_me
          ? "border-subtle bg-elevated"
          : // Someone else's reply is the thing you came to read, so it carries
            // the accent edge rather than sitting flat beside your own.
            "border-accent/40 bg-surface")
      }
    >
      <div className="mb-1 flex items-baseline gap-2 text-[11px]">
        <span className="font-medium text-fg">
          {comment.author_is_me ? "You" : comment.author}
        </span>
        <span className="text-fg-faint" title={new Date(comment.created_at).toLocaleString()}>
          {relativeTime(comment.created_at)}
        </span>
      </div>
      <PageBody text={comment.body} />
    </li>
  );
}
