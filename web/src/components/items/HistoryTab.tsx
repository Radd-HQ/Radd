import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { formatDateTime, relativeTime } from "../../lib/dates";
import { useDurationConfig } from "../../lib/hooks";
import { itemHistoryQuery } from "../../lib/queries";
import { initials } from "../../lib/meta";
import type { HistoryEntry } from "../../lib/types";
import { formatDuration, type DurationConfig } from "../../lib/duration";
import { ChangeList } from "../history/ChangeLines";
import { Spinner } from "../Spinner";

/**
 * The History tab: the item's chronological, actor-attributed activity feed
 * (`GET /items/{id}/history`) — field changes with old→new values, plus comment,
 * worklog, link and MAIL events. Oldest first, matching the composer-at-bottom flow.
 *
 * Mail joined the feed in RADD-984, and the failure leg is why: `mail.failed`
 * was emitted per message and read by nothing, so "the customer never got your
 * reply" existed only in the event table. A failed row is rendered LOUD and
 * carries the relay's own error; a send is rendered like every other row,
 * because the timeline is a ledger, not an alert.
 */
export function HistoryTab({ itemId }: { itemId: string }) {
  const history = useQuery(itemHistoryQuery(itemId));

  if (history.isPending) return <Spinner label="Loading history…" />;
  if (history.isError) {
    return <p className="text-xs text-red-400">Failed to load history: {errorMessage(history.error)}</p>;
  }
  const entries = history.data.entries;
  if (entries.length === 0) {
    return <p className="text-xs text-fg-faint">No changes recorded yet.</p>;
  }
  return (
    <ol className="flex flex-col gap-3.5">
      {entries.map((entry) => (
        <HistoryRow key={entry.id} entry={entry} />
      ))}
    </ol>
  );
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
  const who = entry.actor?.name ?? "System";
  const isUpdate = entry.type === "item.updated";
  // The one row in the feed that is bad news, coloured rather than merely
  // worded so it is findable by scanning (RADD-984).
  const failed = entry.type === "mail.failed";
  const durationConfig = useDurationConfig();
  return (
    <li className="flex gap-2.5">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-strong text-[10px] font-semibold text-fg">
        {initials(who)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
          <span className="font-medium text-fg">{who}</span>
          <span className={failed ? "font-medium text-status-danger-ink" : "text-fg-muted"}>
            {verb(entry, durationConfig)}
          </span>
          <time className="text-fg-faint" dateTime={entry.at} title={formatDateTime(entry.at)}>
            {relativeTime(entry.at)}
          </time>
        </p>
        {isUpdate && entry.changes.length > 0 && (
          <ChangeList changes={entry.changes} className="mt-1" />
        )}
        <SecondaryLine entry={entry} />
      </div>
    </li>
  );
}

/** The row's action phrase (what the actor did). */
function verb(entry: HistoryEntry, durationConfig: DurationConfig): string {
  const detail = entry.detail ?? {};
  switch (entry.type) {
    case "item.created":
      return "created the issue";
    case "item.updated":
      return "made changes";
    case "comment.created":
      return "commented";
    case "comment.updated":
      return "edited a comment";
    case "comment.deleted":
      return "deleted a comment";
    case "worklog.created": {
      const seconds = Number(detail.time_spent_seconds ?? 0);
      return seconds > 0 ? `logged ${formatDuration(seconds, durationConfig)}` : "logged work";
    }
    case "worklog.updated":
      return "updated a worklog";
    case "worklog.deleted":
      return "deleted a worklog";
    case "weblink.created":
      return "added a link";
    case "weblink.updated":
      return "updated a link";
    case "weblink.deleted":
      return "removed a link";
    case "attachment.created":
      return detail.filename ? `attached ${String(detail.filename)}` : "added an attachment";
    case "attachment.deleted":
      return detail.filename
        ? `removed attachment ${String(detail.filename)}`
        : "removed an attachment";
    case "vcs.linked":
      return `linked a ${refTypeLabel(detail)}`;
    case "vcs.updated":
      return `updated a ${refTypeLabel(detail)}`;
    case "vcs.unlinked":
      return `removed a ${refTypeLabel(detail)}`;
    // CSAT (spec 65): both are actorless → rendered as "System …".
    case "csat.requested":
      return "sent the requester a satisfaction survey";
    case "csat.responded": {
      const rating = Number(detail.rating ?? 0);
      return rating > 0
        ? `recorded a ${rating}/5 satisfaction rating`
        : "recorded a satisfaction rating";
    }
    // Approvals (spec 71) — detail carries the gated target state's name.
    case "approval.requested":
      return `requested approval to move to ${String(detail.to_state ?? "?")}`;
    case "approval.voted":
      return detail.verdict === "decline"
        ? `voted to decline the move to ${String(detail.to_state ?? "?")}`
        : `voted to approve the move to ${String(detail.to_state ?? "?")}`;
    case "approval.approved":
      return `approved the move to ${String(detail.to_state ?? "?")}`;
    case "approval.declined":
      return `declined the move to ${String(detail.to_state ?? "?")}`;
    case "approval.canceled":
      return `canceled the approval request for ${String(detail.to_state ?? "?")}`;
    // Participants (spec 72) — detail carries the subject's display name; a
    // `team` ref marks whole-team grants.
    case "item.participant_added":
      return detail.team
        ? `added the ${String(detail.participant ?? "?")} team as participants`
        : `added ${String(detail.participant ?? "?")} as a participant`;
    case "item.participant_removed":
      return detail.team
        ? `removed the ${String(detail.participant ?? "?")} team from participants`
        : `removed participant ${String(detail.participant ?? "?")}`;
    // The mail channel (RADD-984) — all three are actorless, so they render as
    // "System …", which is the truth: a consumer sent them, not a person.
    case "mail.received":
      return detail.sender
        ? `received an email from ${String(detail.sender)}`
        : "received an email";
    case "mail.sent":
      return `emailed ${mailAudience(detail)}`;
    case "mail.failed":
      return `could not email ${mailAudience(detail)}`;
    default:
      return entry.type;
  }
}

/**
 * Who a mail event was addressed to. `recipients` is a list on the wire even
 * though the transport emits one event per message — reading the count rather
 * than assuming arity is what keeps this row honest if that ever batches again.
 */
function mailAudience(detail: Record<string, unknown>): string {
  const recipients = Array.isArray(detail.recipients) ? detail.recipients : [];
  const count = Number(detail.recipient_count ?? recipients.length);
  if (recipients.length === 1) return String(recipients[0]);
  if (count > 1) return `${count} recipients`;
  return "the recipient";
}

function refTypeLabel(detail: Record<string, unknown>): string {
  const type = String(detail.ref_type ?? "reference");
  return type.replace(/_/g, " ");
}

/** A URL/comment secondary line for events that carry a link or internal marker. */
function SecondaryLine({ entry }: { entry: HistoryEntry }) {
  const detail = entry.detail ?? {};
  if (entry.type.startsWith("comment.") && detail.visibility === "internal") {
    return <p className="mt-0.5 text-[11px] text-amber-300/80">Internal note</p>;
  }
  // A delivery failure says WHAT the relay said and whether anyone will try
  // again — the two facts an agent needs before re-answering by hand (RADD-984).
  if (entry.type === "mail.failed") {
    const error = typeof detail.error === "string" ? detail.error : "";
    return (
      <p className="mt-0.5 text-[11px] text-status-danger-ink">
        {detail.given_up ? "Delivery failed — no further attempts." : "Delivery failed."}
        {error ? ` ${error}` : ""}
      </p>
    );
  }
  const url = typeof detail.url === "string" ? detail.url : null;
  const title = typeof detail.title === "string" && detail.title ? detail.title : url;
  if (url && (entry.type.startsWith("weblink.") || entry.type.startsWith("vcs."))) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="mt-0.5 block truncate text-[13px] text-accent-text hover:underline"
      >
        {title}
      </a>
    );
  }
  return null;
}
