import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api, ErrorText, ItemKeyLink, ItemPeek, shortDate, Entity } from "@radd/plugin-sdk";

/** The My Work widget key — `ApprovalWidget.AWAITING` on the manifest's `WidgetTypeSpec`. */
export const AWAITING_WIDGET = "approvals";

/** One row of GET /approvals/pending. */
interface PendingApproval {
  id: string;
  item_id: string;
  item_key: string;
  item_title: string;
  to_state_name: string;
  requested_by: { id: string; name: string } | null;
  note: string;
  created_at: string;
}

/** Tagged `item`: a vote or a move changes the queue, and both are item events. */
const pendingApprovalsQuery = {
  queryKey: ["approvals", "pending"] as const,
  meta: { entities: [Entity.item] },
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<PendingApproval[]>("/approvals/pending", { signal }),
};

/** "Awaiting my approval" (spec 71) — My Work widget; rows open the peek. */
export function AwaitingApproval() {
  const pending = useQuery(pendingApprovalsQuery);
  const rows = pending.data ?? [];
  if (pending.isError) return <ErrorText error={pending.error} />;
  if (pending.isPending) return <p className="text-sm text-fg-muted">Loading approvals…</p>;
  if (rows.length === 0) return <p className="text-sm text-fg-muted" data-approvals-empty>No approvals waiting for you.</p>;
  return (
    <section data-approvals-awaiting>
      <header className="mb-2 flex items-center gap-2">
        <ShieldCheck size={14} className="text-fg-muted" aria-hidden />
        <h2 className="text-sm font-semibold text-fg">Awaiting my approval</h2>
        <span className="text-xs text-fg-faint">{rows.length}</span>
      </header>
      <ul className="overflow-hidden rounded-lg border border-subtle">
        {rows.map((row) => (
          <li key={row.id}>
            <ItemPeek itemKey={row.item_key}>{(open) => (
              <div role="button" tabIndex={0} onClick={open} onKeyDown={(event) => { if (event.key === "Enter") open(); }}
                title={row.note || undefined}
                className="flex w-full cursor-pointer items-center gap-2.5 border-b border-subtle/60 px-4 py-2 text-left last:border-b-0 hover:bg-elevated/50">
                <ItemKeyLink itemKey={row.item_key}
                  className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary hover:text-accent-text hover:underline" />
                <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{row.item_title}</span>
                <span className="shrink-0 rounded bg-elevated/80 px-1.5 py-px text-[10px] text-fg-secondary">→ {row.to_state_name}</span>
                <span className="shrink-0 text-[11px] text-fg-muted">{row.requested_by?.name ?? "Unknown"} · {shortDate(row.created_at)}</span>
              </div>
            )}</ItemPeek>
          </li>
        ))}
      </ul>
    </section>
  );
}
