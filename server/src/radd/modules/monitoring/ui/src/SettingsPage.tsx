import { useQuery } from "@tanstack/react-query";
import { Activity, Database } from "lucide-react";
import { api, QueryError, SettingsPage, Spinner, Slot, SlotId } from "@radd/plugin-sdk";
import type { MonitoringOverview, WorkerStatus } from "./types";
import { Card, StatRow } from "./cards";

const OVERVIEW_POLL_MS = 5_000;
/** A consumer with backlog whose cursor hasn't moved in this long is stalled. */
const STALL_AFTER_SECONDS = 120;

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

type WorkerState = "ok" | "catching_up" | "stalled" | "retired";

/** Zero lag = fine no matter how old the cursor is (idle stream). Backlog is
 * fine while the cursor keeps moving; backlog + a frozen cursor = stalled. */
function workerState(worker: WorkerStatus): WorkerState {
  // RADD-1093: a cursor no running code claims is residue (a rename, or a
  // disabled plugin) — its backlog will grow forever and means nothing.
  if (!worker.registered) return "retired";
  if (worker.lag === 0) return "ok";
  return worker.seconds_since_update > STALL_AFTER_SECONDS ? "stalled" : "catching_up";
}

const WORKER_STATE_STYLES: Record<WorkerState, { label: string; className: string }> = {
  ok: { label: "OK", className: "bg-status-success/15 text-status-success ring-status-success/30" },
  catching_up: {
    label: "Catching up",
    className: "bg-accent/15 text-accent-text ring-accent/30",
  },
  stalled: { label: "Stalled", className: "bg-status-danger/15 text-status-danger ring-status-danger/30" },
  retired: { label: "Retired", className: "bg-surface text-fg-muted ring-strong" },
};

/** Operator monitoring (admin-only): DB health, entity counts, embedding
 * coverage, and each background worker's event-stream lag. Polls while open. */
export function MonitoringSettingsPage() {
  const overview = useQuery({
    queryKey: ["monitoringOverview"],
    queryFn: ({ signal }) => api.get<MonitoringOverview>("/monitoring/overview", { signal }),
    refetchInterval: OVERVIEW_POLL_MS,
    staleTime: 0, gcTime: 0,
  });

  if (overview.isPending) return <Spinner />;
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
      description="Live health of this instance: database, background workers, outbound mail, and index coverage. Refreshes every few seconds while open."
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Card icon={Database} title="Database">
          <StatRow
            label="Status"
            value={
              <span className="inline-flex items-center gap-1.5">
                <span
                  className={`size-2 rounded-full ${data.database.ok ? "bg-status-success" : "bg-status-danger"}`}
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

        <Slot id={SlotId.settingsSection} match="monitoring" />

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
                        {worker.description || "Background consumer"}
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
