import { useQuery } from "@tanstack/react-query";
import { Inbox } from "lucide-react";
import { errorMessage } from "../../lib/api";
import { relativeTime } from "../../lib/dates";
import { portalRequestsQuery } from "../../lib/queries";

/**
 * What this person has filed (RADD-785).
 *
 * Shared by `/portal` and My Work so the two cannot drift — a requester meets
 * this list on whichever page they land on, and there is only one definition of
 * what a request looks like from the outside.
 *
 * No link to the issue. That is deliberate rather than an omission: the whole
 * point is that a requester may hold no `item.read` anywhere, so `/issues/KEY`
 * would answer them a permission error. What they get is the state their
 * request is in, which is the question they actually have.
 */
export function MyRequests({ compact = false }: { compact?: boolean }) {
  const requests = useQuery(portalRequestsQuery);

  if (requests.isPending) return null;
  if (requests.isError) {
    return <p className="text-sm text-red-400">{errorMessage(requests.error)}</p>;
  }
  const rows = requests.data;
  if (rows.length === 0) return null;

  return (
    <section className="flex flex-col gap-2" aria-label="My requests">
      <h2 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
        <Inbox size={12} aria-hidden />
        My requests
      </h2>
      <ul className="flex flex-col rounded-lg border border-subtle bg-surface">
        {(compact ? rows.slice(0, 5) : rows).map((request) => (
          <li
            key={request.key}
            className="flex items-baseline gap-2 border-b border-subtle/60 px-3 py-2 text-[13px] last:border-b-0"
          >
            <span className="shrink-0 font-mono text-[11px] text-fg-muted">{request.key}</span>
            <span className="min-w-0 flex-1 truncate text-fg">{request.title}</span>
            <span className="shrink-0 rounded border border-strong px-1.5 py-px text-[11px] text-fg-secondary">
              {request.state || "—"}
            </span>
            <span
              className="shrink-0 text-[11px] text-fg-faint"
              title={new Date(request.updated_at).toLocaleString()}
            >
              {relativeTime(request.updated_at)}
            </span>
          </li>
        ))}
      </ul>
      {compact && rows.length > 5 && (
        <p className="text-[11px] text-fg-faint">
          Showing 5 of {rows.length} — the Portal has the rest.
        </p>
      )}
    </section>
  );
}
