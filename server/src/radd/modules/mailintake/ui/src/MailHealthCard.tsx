import { useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";
import { api, Card, QueryError, Spinner, formatDateTime } from "@radd/plugin-sdk";
import type { ReactNode } from "react";

/** One message the relay refused (RADD-1036). */
export interface MailFailureEntry {
  at: string;
  recipient: string;
  subject: string;
  /** The exception's class and message, capped by the emitter. */
  error: string;
  /** The retry ladder ran out — nobody is going to hear from us. */
  given_up: boolean;
}

/** Outbound mail over the recent window, served only while Mail is enabled. */
export interface MailHealth {
  window_hours: number;
  failures: number;
  given_up: number;
  /** True when the scan hit its limit; `failures` is a floor, not a count. */
  capped: boolean;
  recent: MailFailureEntry[];
}

function StatRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-[13px] text-fg-secondary">{label}</span>
      <span className="text-[13px] font-medium tabular-nums text-heading">{value}</span>
    </div>
  );
}

function formatAt(iso: string): string {
  return Number.isNaN(Date.parse(iso)) ? iso : formatDateTime(iso);
}

/** Outbound mail over the last day (RADD-1036).
 *
 * A terminally-failed message used to exist only as two events in a stream
 * nobody aggregated: the retry ladder gives up, stamps the row, and "the
 * customer never got it" was knowable only by querying the events table. The
 * card is deliberately quiet at zero — an operator page that shouts when
 * nothing is wrong is one nobody reads when something is. */
export function MailHealthCard() {
  const query = useQuery({ queryKey: ["mailHealth"], queryFn: ({ signal }) => api.get<MailHealth>("/mail/health", { signal }), refetchInterval: 5000, staleTime: 0, gcTime: 0 });
  if (query.isPending) return <Spinner />;
  if (query.isError) return <QueryError label="outbound mail health" error={query.error} />;
  const mail = query.data;
  const healthy = mail.failures === 0;
  return (
    <Card title={<span className="flex items-center gap-1.5"><Mail size={13} aria-hidden />Outbound mail</span>}>
      <StatRow
        label={`Failures (last ${mail.window_hours}h)`}
        value={
          <span className="inline-flex items-center gap-1.5">
            <span
              className={`size-2 rounded-full ${healthy ? "bg-status-success" : "bg-status-danger"}`}
              aria-hidden
            />
            {healthy ? "None" : `${mail.failures.toLocaleString()}${mail.capped ? "+" : ""}`}
          </span>
        }
      />
      {mail.given_up > 0 && (
        <StatRow
          label="Given up on (never delivered)"
          value={<span className="text-status-danger">{mail.given_up.toLocaleString()}</span>}
        />
      )}
      {mail.recent.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-fg-faint">
                <th className="py-1 pr-3 font-medium">When</th>
                <th className="py-1 pr-3 font-medium">Recipient</th>
                <th className="py-1 font-medium">Error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle/60">
              {mail.recent.map((failure, index) => (
                <tr key={`${failure.at}-${failure.recipient}-${index}`}>
                  <td className="whitespace-nowrap py-1.5 pr-3 tabular-nums text-fg-secondary">
                    {formatAt(failure.at)}
                  </td>
                  <td className="py-1.5 pr-3 text-fg" title={failure.subject}>
                    {failure.recipient || "—"}
                    {failure.given_up && (
                      <span className="ml-1.5 rounded-full bg-status-danger/15 px-2 py-0.5 text-[11px] font-medium text-status-danger ring-1 ring-status-danger/30">
                        Gave up
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 text-fg-muted">{failure.error || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {healthy && (
        <p className="mt-2 text-xs text-fg-muted">
          Every message sent in the last {mail.window_hours} hours was accepted by the relay.
        </p>
      )}
    </Card>
  );
}

