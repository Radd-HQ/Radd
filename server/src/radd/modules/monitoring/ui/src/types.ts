/** Operator monitoring (Settings → Monitoring, admin-only). */

export interface DatabaseHealth {
  ok: boolean;
  postgres_version: string;
  size_bytes: number;
  active_connections: number;
}

export interface EntityCount {
  key: string;
  label: string;
  /** Approximate — Postgres live-tuple estimate, instant at any corpus size. */
  count: number;
}

export interface WorkerStatus {
  /** False = no running code claims this cursor (RADD-1093): rename residue
   * or a disabled plugin — shown as Retired, never Stalled. */
  registered: boolean;
  name: string;
  description: string;
  last_event_id: number;
  stream_head: number;
  lag: number;
  seconds_since_update: number;
  /** RADD-1538: events this worker's handler raised on — retrying / given up on. */
  failed_pending?: number;
  failed_dead?: number;
}

export interface ConsumerFailure {
  id: number;
  consumer: string;
  event_id: number;
  status: "pending" | "dead";
  attempts: number;
  error: string;
  next_attempt_at: string | null;
  first_failed_at: string;
  last_failed_at: string;
  /** Null when the event itself was pruned from the ledger. */
  event_type: string | null;
  entity_label: string | null;
}

export interface ReplayResult {
  delivered: boolean;
  failure: ConsumerFailure | null;
}

export interface MonitoringOverview {
  database: DatabaseHealth;
  counts: EntityCount[];
  workers: WorkerStatus[];
  /** False = web-only process; the consumers run in a separate worker process. */
  workers_in_process: boolean;
}
