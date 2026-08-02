import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { errorMessage } from "../../lib/api";
import { relativeTime } from "../../lib/dates";
import { useDurationConfig } from "../../lib/hooks";
import { itemHistoryQuery } from "../../lib/queries";
import { HISTORY_FIELD_LABELS, PRIORITY_META, initials } from "../../lib/meta";
import type { HistoryChange, HistoryEntry, LinkChangeRef, PriorityValue } from "../../lib/types";
import { formatDuration, type DurationConfig } from "../../lib/duration";
import { Spinner } from "../Spinner";

/**
 * The History tab: the item's chronological, actor-attributed activity feed
 * (`GET /items/{id}/history`) — field changes with old→new values, plus comment,
 * worklog, and link events. Oldest first, matching the composer-at-bottom flow.
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
  const durationConfig = useDurationConfig();
  return (
    <li className="flex gap-2.5">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-strong text-[10px] font-semibold text-fg">
        {initials(who)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
          <span className="font-medium text-fg">{who}</span>
          <span className="text-fg-muted">{verb(entry, durationConfig)}</span>
          <time className="text-fg-faint" dateTime={entry.at} title={new Date(entry.at).toLocaleString()}>
            {relativeTime(entry.at)}
          </time>
        </p>
        {isUpdate && entry.changes.length > 0 && (
          <ul className="mt-1 flex flex-col gap-0.5">
            {entry.changes.map((change, index) => (
              <li key={index} className="text-[13px] leading-relaxed text-fg">
                <ChangeLine change={change} />
              </li>
            ))}
          </ul>
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
    default:
      return entry.type;
  }
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

function ChangeLine({ change }: { change: HistoryChange }): ReactNode {
  const label =
    change.field === "custom_field"
      ? change.name ?? "Field"
      : HISTORY_FIELD_LABELS[change.field] ?? change.field;

  if (change.field === "description") {
    return (
      <>
        <FieldLabel>{label}</FieldLabel> changed
      </>
    );
  }
  if (change.field === "flagged") {
    return change.to ? "Flagged this issue" : "Removed the flag";
  }
  if (change.field === "labels") {
    return (
      <>
        <FieldLabel>{label}</FieldLabel> <ChipDelta added={asStrings(change.added)} removed={asStrings(change.removed)} />
      </>
    );
  }
  if (change.field === "links") {
    return (
      <>
        <FieldLabel>{label}</FieldLabel> <LinkDelta added={asLinks(change.added)} removed={asLinks(change.removed)} />
      </>
    );
  }
  return (
    <>
      <FieldLabel>{label}:</FieldLabel>{" "}
      <ValueSpan field={change.field} value={change.from} muted />
      <ArrowRight size={12} className="mx-1 inline align-[-1px] text-fg-faint" aria-hidden />
      <ValueSpan field={change.field} value={change.to} />
    </>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="text-fg-muted">{children}</span>;
}

function ValueSpan({
  field,
  value,
  muted = false,
}: {
  field: string;
  value: HistoryChange["from"];
  muted?: boolean;
}) {
  const text = formatValue(field, value);
  return <span className={muted ? "text-fg-muted line-through" : "text-heading"}>{text}</span>;
}

function formatValue(field: string, value: HistoryChange["from"]): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field === "priority") {
    const meta = PRIORITY_META[value as PriorityValue];
    if (meta) return meta.label;
  }
  return String(value);
}

function ChipDelta({ added, removed }: { added: string[]; removed: string[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {added.map((name) => (
        <span key={`+${name}`} className="text-emerald-400">
          +{name}
        </span>
      ))}
      {removed.map((name) => (
        <span key={`-${name}`} className="text-red-400">
          −{name}
        </span>
      ))}
    </span>
  );
}

function LinkDelta({ added, removed }: { added: LinkChangeRef[]; removed: LinkChangeRef[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {added.map((link) => (
        <span key={`+${link.key}`} className="text-emerald-400">
          +{link.key} ({link.link_type})
        </span>
      ))}
      {removed.map((link) => (
        <span key={`-${link.key}`} className="text-red-400">
          −{link.key} ({link.link_type})
        </span>
      ))}
    </span>
  );
}

function asStrings(value: HistoryChange["added"]): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function asLinks(value: HistoryChange["added"]): LinkChangeRef[] {
  return Array.isArray(value)
    ? value.filter((v): v is LinkChangeRef => typeof v === "object" && v !== null)
    : [];
}
