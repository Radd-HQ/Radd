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

/** Outbound mail over the recent window. `available: false` = the mailintake
 * module is not loaded, which is not a health problem: the card is absent
 * rather than green. */
export interface MailHealth {
  available: boolean;
  window_hours: number;
  failures: number;
  given_up: number;
  /** True when the scan hit its limit; `failures` is a floor, not a count. */
  capped: boolean;
  recent: MailFailureEntry[];
}

export interface MonitoringOverview {
  database: DatabaseHealth;
  counts: EntityCount[];
  workers: WorkerStatus[];
  /** False = web-only process; the consumers run in a separate worker process. */
  workers_in_process: boolean;
  mail: MailHealth;
}
