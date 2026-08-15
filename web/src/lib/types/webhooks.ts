/** Settings → Webhooks (RADD-1096). */

export interface WebhookEndpoint {
  id: string;
  url: string;
  /** The Standard-Webhooks signing secret (whsec_…) — the receiver needs it. */
  secret: string;
  description: string;
  event_types: string[] | null;
  active: boolean;
  created_at: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  event_id: number;
  status: string;
  attempts: number;
  next_attempt_at: string;
  last_status_code: number | null;
  last_error: string | null;
  created_at: string;
}
