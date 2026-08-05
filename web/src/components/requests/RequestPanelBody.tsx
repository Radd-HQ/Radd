import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Package, UserRound } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import { portalRequestDetailQuery, queryKeys } from "../../lib/queries";
import type { PortalRequestComment } from "../../lib/types";
import { Button } from "../Button";
import { PageBody } from "../pages/PageBody";
import { Spinner } from "../Spinner";
import { ErrorText } from "../ErrorText";

/**
 * A requester's view of one request, rendered INSIDE the ordinary peek drawer
 * (RADD-803).
 *
 * The first version of this was a centred modal, which was a mistake worth
 * recording: RADD-796 asked for "a peek-shaped surface", and a modal is a NEW
 * interaction pattern in an app where every other "open this row" is the
 * right-hand drawer. It was chosen because `IssuePanel` resolves through
 * `item.read` — the thing a requester lacks — and a modal was the shortest path
 * to something that opened. Shorter was not the requirement.
 *
 * So this is a BODY, not a panel: `IssuePanel` owns the drawer, and picks
 * between `ItemDetailBody` and this by what the reader may actually see. One
 * `?peek=` param, one drawer, one implementation of "open a row".
 *
 * Content is the requester's entitlement and no more — state, who holds it,
 * what shipped it, the PUBLIC thread, and a way to reply. A requester who
 * cannot answer a question asked of them is stuck.
 */
export function RequestPanelBody({ requestKey }: { requestKey: string }) {
  const queryClient = useQueryClient();
  const detail = useQuery(portalRequestDetailQuery(requestKey));
  const [reply, setReply] = useState("");

  const send = useMutation({
    mutationFn: () =>
      api.post(`${ApiPath.portalRequests}/${requestKey}/comments`, { body: reply }),
    onSuccess: async () => {
      setReply("");
      // The thread AND the list change: replying clears the row's marker.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.portalRequest(requestKey) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.portalRequests }),
      ]);
    },
  });

  if (detail.isPending) return <Spinner label="Loading…" />;
  if (detail.isError || !detail.data) {
    return <p className="p-6 text-sm text-fg-muted">Request {requestKey} not found.</p>;
  }
  const request = detail.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-3">
      <h1 className="text-base font-semibold text-heading">{request.title}</h1>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-fg-secondary">
        <span className="rounded border border-strong px-1.5 py-px">{request.state || "—"}</span>
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
        <div className="mt-3 rounded-lg border border-subtle bg-surface px-3 py-2">
          <PageBody text={request.description} />
        </div>
      )}

      <section className="mt-4 flex flex-col gap-2" aria-label="Conversation">
        <h2 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
          <MessageSquare size={12} aria-hidden />
          Conversation
        </h2>
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

      <div className="mt-3 flex flex-col gap-2">
        <textarea
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          rows={3}
          placeholder="Add a reply…"
          aria-label="Reply to this request"
          className="w-full rounded-md border border-subtle bg-base px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus-visible:outline-2 focus-visible:outline-focus"
        />
        {send.isError && <ErrorText error={send.error} />}
        <div className="flex justify-end">
          <Button onClick={() => send.mutate()} disabled={!reply.trim() || send.isPending}>
            {send.isPending ? "Sending…" : "Reply"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function CommentBubble({ comment }: { comment: PortalRequestComment }) {
  return (
    <li
      className={
        "rounded-lg border px-3 py-2 " +
        (comment.author_is_me
          ? "border-subtle bg-elevated"
          : // Someone else's reply is what you came to read, so it carries the
            // accent edge rather than sitting flat beside your own.
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
