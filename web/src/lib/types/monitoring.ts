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
  name: string;
  last_event_id: number;
  stream_head: number;
  lag: number;
  seconds_since_update: number;
}

export interface MonitoringOverview {
  database: DatabaseHealth;
  counts: EntityCount[];
  workers: WorkerStatus[];
  /** False = web-only process; the consumers run in a separate worker process. */
  workers_in_process: boolean;
}
