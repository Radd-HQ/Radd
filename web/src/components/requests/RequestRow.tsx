import { MessageSquare, Package, UserRound } from "lucide-react";
import { relativeTime } from "../../lib/dates";
import { StateCategory, type PortalRequest } from "../../lib/types";

/**
 * One request, as its requester sees it (RADD-797).
 *
 * ONE definition, rendered by both `/portal` and My Work (RADD-799). They used
 * to draw the same row two different ways, which is how they drifted apart in
 * the first place.
 *
 * Everything here is inside the relationship boundary the portal is built on: a
 * NAME from the member-floor directory, a version string, and a count derived
 * from PUBLIC comments only. No description, no labels, no fields — opening the
 * request is a separate, deliberate act.
 */

/** Category → the workflow palette the rest of the app uses. */
const CATEGORY_STYLE: Record<string, string> = {
  [StateCategory.triage]: "border-strong text-fg-secondary",
  [StateCategory.backlog]: "border-strong text-fg-secondary",
  [StateCategory.todo]: "border-strong text-fg-secondary",
  [StateCategory.in_progress]: "border-amber-500/40 text-amber-300",
  [StateCategory.done]: "border-emerald-500/40 text-emerald-300",
  [StateCategory.canceled]: "border-strong text-fg-faint",
};

export function RequestRow({
  request,
  onOpen,
}: {
  request: PortalRequest;
  onOpen: (key: string) => void;
}) {
  return (
    <li className="border-b border-subtle/60 last:border-b-0">
      {/*
        A BUTTON, not a link. `/issues/KEY` resolves through `item.read`, which a
        requester holds nowhere — the reason these rows were inert until now.
        This opens the requester view instead (RADD-796).
      */}
      <button
        type="button"
        onClick={() => onOpen(request.key)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] cursor-pointer hover:bg-elevated focus-visible:outline-2 focus-visible:outline-focus"
      >
        {/*
          The "someone answered you" dot. Given a fixed 10px gutter rather than
          rendered conditionally, so a row does not shift sideways when a reply
          lands — a list that reflows as you read it is worse than no marker.
        */}
        <span className="flex w-2.5 shrink-0 justify-center" aria-hidden={!request.awaiting_requester}>
          {request.awaiting_requester && (
            <span
              className="size-2 rounded-full bg-accent"
              title="Someone replied — this is waiting on you"
            />
          )}
        </span>
        <span className="shrink-0 font-mono text-[11px] text-fg-muted">{request.key}</span>
        <span
          className={
            "min-w-0 flex-1 truncate " +
            (request.awaiting_requester ? "font-medium text-heading" : "text-fg")
          }
        >
          {request.title}
        </span>

        {request.comment_count > 0 && (
          <span
            className="flex shrink-0 items-center gap-0.5 text-[11px] text-fg-faint"
            title={`${request.comment_count} ${request.comment_count === 1 ? "reply" : "replies"}`}
          >
            <MessageSquare size={11} aria-hidden />
            {request.comment_count}
          </span>
        )}
        {request.release && (
          <span
            className="hidden shrink-0 items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] text-fg-secondary sm:flex"
            title={`Shipped in ${request.release}`}
          >
            <Package size={10} aria-hidden />
            {request.release}
          </span>
        )}
        <span
          className="hidden shrink-0 items-center gap-1 text-[11px] text-fg-faint sm:flex"
          title={request.assignee ? `Assigned to ${request.assignee}` : "Nobody has picked this up yet"}
        >
          <UserRound size={11} aria-hidden />
          {request.assignee ?? "Unassigned"}
        </span>
        <span
          className={
            "shrink-0 rounded border px-1.5 py-px text-[11px] " +
            (CATEGORY_STYLE[request.state_category] ?? "border-strong text-fg-secondary")
          }
        >
          {request.state || "—"}
        </span>
        <span
          className="hidden shrink-0 text-[11px] text-fg-faint md:inline"
          title={new Date(request.updated_at).toLocaleString()}
        >
          {relativeTime(request.updated_at)}
        </span>
      </button>
    </li>
  );
}
