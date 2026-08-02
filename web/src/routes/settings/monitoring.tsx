import { useQuery } from "@tanstack/react-query";
import { Activity, Database, Sparkles } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import type { EmbeddingCoverage, MonitoringOverview, WorkerStatus } from "../../lib/types";
import { QueryError } from "../../components/QueryError";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { Spinner } from "../../components/Spinner";

const OVERVIEW_POLL_MS = 5_000;
/** A consumer with backlog whose cursor hasn't moved in this long is stalled. */
const STALL_AFTER_SECONDS = 120;

/** What each background consumer does — shown next to its lag. */
const WORKER_DESCRIPTIONS: Record<string, string> = {
  "notify.consumer": "Turns events into notifications and emails",
  "webhooks.dispatcher": "Delivers webhook calls",
  "automations.engine": "Runs automation rules",
  "search.indexer": "Keeps full-text search fresh",
  "ai.embedder": "Builds semantic-search vectors",
  "attachments.gc": "Removes orphaned attachment bytes",
  "csat.sender": "Sends satisfaction surveys",
  "mailintake.outbound": "Sends outbound mail replies",
};

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function formatAgo(seconds: number): string {
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

type WorkerState = "ok" | "catching_up" | "stalled";

/** Zero lag = fine no matter how old the cursor is (idle stream). Backlog is
 * fine while the cursor keeps moving; backlog + a frozen cursor = stalled. */
function workerState(worker: WorkerStatus): WorkerState {
  if (worker.lag === 0) return "ok";
  return worker.seconds_since_update > STALL_AFTER_SECONDS ? "stalled" : "catching_up";
}

const WORKER_STATE_STYLES: Record<WorkerState, { label: string; className: string }> = {
  ok: { label: "OK", className: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30" },
  catching_up: {
    label: "Catching up",
    className: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  },
  stalled: { label: "Stalled", className: "bg-red-500/15 text-red-300 ring-red-500/30" },
};

function Card({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Database;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-subtle bg-surface p-4 shadow-lift">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <Icon size={13} aria-hidden />
        {title}
      </h3>
      {children}
    </section>
  );
}

function StatRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-[13px] text-fg-secondary">{label}</span>
      <span className="text-[13px] font-medium tabular-nums text-heading">{value}</span>
    </div>
  );
}

/** Operator monitoring (admin-only): DB health, entity counts, embedding
 * coverage, and each background worker's event-stream lag. Polls while open. */
export function MonitoringSettingsPage() {
  const overview = useQuery({
    queryKey: queryKeys.monitoringOverview,
    queryFn: () => api.get<MonitoringOverview>(ApiPath.monitoringOverview),
    refetchInterval: OVERVIEW_POLL_MS,
  });
  // Semantic-index coverage comes from the ai module — composed here so
  // monitoring works with the ai plugin disabled (this query just 404s away).
  const coverage = useQuery({
    queryKey: queryKeys.aiEmbeddingCoverage,
    queryFn: () => api.get<EmbeddingCoverage>(ApiPath.aiEmbeddingCoverage),
    refetchInterval: OVERVIEW_POLL_MS,
    retry: false,
  });

  if (overview.isPending) return <Spinner label="Loading monitoring…" />;
  if (overview.isError)
    return (
      <div className="p-8">
        <QueryError label="monitoring" error={overview.error} />
      </div>
    );
  const data = overview.data;

  return (
    <SettingsPage
      title="Monitoring"
      description="Live health of this instance: database, background workers, and index coverage. Refreshes every few seconds while open."
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Card icon={Database} title="Database">
          <StatRow
            label="Status"
            value={
              <span className="inline-flex items-center gap-1.5">
                <span
                  className={`size-2 rounded-full ${data.database.ok ? "bg-emerald-400" : "bg-red-400"}`}
                  aria-hidden
                />
                {data.database.ok ? "Connected" : "Unreachable"}
              </span>
            }
          />
          <StatRow label="PostgreSQL" value={data.database.postgres_version} />
          <StatRow label="Database size" value={formatBytes(data.database.size_bytes)} />
          <StatRow label="Active connections" value={data.database.active_connections} />
        </Card>

        <Card icon={Activity} title="Contents (approximate)">
          <div className="grid grid-cols-2 gap-x-6">
            {data.counts.map((entry) => (
              <StatRow
                key={entry.key}
                label={entry.label}
                value={entry.count.toLocaleString()}
              />
            ))}
          </div>
        </Card>

        {coverage.data?.enabled && (
          <Card icon={Sparkles} title="Semantic index">
            <StatRow
              label="Issues embedded"
              value={`${coverage.data.items_embedded.toLocaleString()} / ${coverage.data.items_total.toLocaleString()}`}
            />
            <StatRow
              label="Wiki pages embedded"
              value={`${coverage.data.docs_embedded.toLocaleString()} / ${coverage.data.docs_total.toLocaleString()}`}
            />
            {(coverage.data.items_embedded < coverage.data.items_total ||
              coverage.data.docs_embedded < coverage.data.docs_total) && (
              <p className="mt-2 text-xs text-fg-muted">
                Backfill in progress — the embedder works through the backlog in batches.
              </p>
            )}
          </Card>
        )}

        <Card icon={Activity} title="Background workers">
          {!data.workers_in_process && (
            <p className="mb-2 text-xs text-fg-muted">
              This API process runs web-only — the workers live in a separate process; lag
              below still reflects their real progress.
            </p>
          )}
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-fg-faint">
                <th className="py-1 pr-3 font-medium">Worker</th>
                <th className="py-1 pr-3 font-medium">Backlog</th>
                <th className="py-1 pr-3 font-medium">Last movement</th>
                <th className="py-1 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle/60">
              {data.workers.map((worker) => {
                const state = WORKER_STATE_STYLES[workerState(worker)];
                return (
                  <tr key={worker.name}>
                    <td className="py-1.5 pr-3">
                      <span className="font-mono text-xs text-fg">{worker.name}</span>
                      <span className="block text-[11px] text-fg-muted">
                        {WORKER_DESCRIPTIONS[worker.name] ?? "Background consumer"}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 tabular-nums text-fg-secondary">
                      {worker.lag === 0 ? "caught up" : `${worker.lag.toLocaleString()} events`}
                    </td>
                    <td
                      className="py-1.5 pr-3 tabular-nums text-fg-secondary"
                      title={`cursor at event ${worker.last_event_id.toLocaleString()} of ${worker.stream_head.toLocaleString()}`}
                    >
                      {formatAgo(worker.seconds_since_update)}
                    </td>
                    <td className="py-1.5">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${state.className}`}
                      >
                        {state.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </div>
    </SettingsPage>
  );
}
