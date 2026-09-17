/** Attachment storage hosts (spec 102) — Settings → Storage. */

/** Where a host's bytes live: a local filesystem root, or an S3-compatible endpoint. */
export const StorageHostType = {
  filesystem: "filesystem",
  s3: "s3",
} as const;
export type StorageHostTypeValue = (typeof StorageHostType)[keyof typeof StorageHostType];

/** How bytes reach the browser: proxied through the API, or a 307 to a short
 * presigned URL on the host itself (network reachability then gates readers). */
export const DeliveryMode = {
  proxy: "proxy",
  presigned: "presigned",
} as const;
export type DeliveryModeValue = (typeof DeliveryMode)[keyof typeof DeliveryMode];

/** Where a host row came from — env-seeded rows are ordinary editable rows. */
export const StorageHostSource = {
  env: "env",
  user: "user",
} as const;
export type StorageHostSourceValue = (typeof StorageHostSource)[keyof typeof StorageHostSource];

/** One host row from GET /storage/hosts — the secret never leaves the server. */
export interface StorageHostRead {
  id: string;
  name: string;
  host_type: StorageHostTypeValue;
  /** s3 only: host:port, no scheme. */
  endpoint: string;
  access_key: string;
  has_secret_key: boolean;
  bucket: string;
  region: string;
  secure: boolean;
  /** filesystem only; "" = the server's configured default directory. */
  root_dir: string;
  delivery_mode: DeliveryModeValue;
  /** null = the server-wide default expiry. */
  presign_expiry_seconds: number | null;
  user_selectable: boolean;
  email_images_allowed: boolean;
  is_default: boolean;
  source: StorageHostSourceValue;
  /** Filled server-side from one grouped count query. */
  attachment_count: number;
  total_bytes: number;
}

/** POST /storage/hosts body. */
export interface StorageHostCreatePayload {
  name: string;
  host_type: StorageHostTypeValue;
  endpoint?: string;
  access_key?: string;
  secret_key?: string;
  bucket?: string;
  region?: string;
  secure?: boolean;
  root_dir?: string;
  delivery_mode?: DeliveryModeValue;
  presign_expiry_seconds?: number | null;
  user_selectable?: boolean;
  email_images_allowed?: boolean;
  is_default?: boolean;
}

/** PATCH /storage/hosts/{id} body — host_type is immutable; "" secret = keep stored. */
export type StorageHostUpdatePayload = Omit<StorageHostCreatePayload, "host_type">;

/** GET /storage/hosts/{id}/health — a live probe; failures come back as data. */
export interface StorageHostHealth {
  ok: boolean;
  detail: string;
}

/** Builtin routing-rule types (spec 102); plugins can contribute more later. */
export const StorageRuleType = {
  userChoice: "user_choice",
  cidr: "cidr",
  llm: "llm",
} as const;
export type StorageRuleTypeValue = (typeof StorageRuleType)[keyof typeof StorageRuleType];

/** cidr config: the first range containing the uploader's address wins. */
export interface CidrRange {
  cidr: string;
  host_id: string;
}

/** llm config: one ENUMERATED answer → host (the model can't invent more). */
export interface LlmAnswer {
  answer: string;
  host_id: string;
}

/** Per-type payloads in one bag: user_choice {}, cidr {ranges}, llm the rest.
 * Invalid combinations 422 server-side with a detail the dialog surfaces. */
export interface StorageRuleConfig {
  ranges?: CidrRange[];
  prompt?: string;
  answers?: LlmAnswer[];
  content_type_prefixes?: string[];
  timeout_seconds?: number;
}

/** One chain row from GET /storage/rules (position-ordered, top-down). */
export interface StorageRuleRead {
  id: string;
  name: string;
  rule_type: StorageRuleTypeValue;
  position: number;
  enabled: boolean;
  config: StorageRuleConfig;
}

/** POST /storage/rules body. */
export interface StorageRuleCreatePayload {
  name: string;
  rule_type: StorageRuleTypeValue;
  config: StorageRuleConfig;
  enabled?: boolean;
}

/** PATCH /storage/rules/{id} body — rule_type is immutable after creation. */
export interface StorageRuleUpdatePayload {
  name?: string;
  config?: StorageRuleConfig;
  enabled?: boolean;
}

/** One offered host from GET /storage/upload-context. */
export interface UploadOption {
  id: string;
  name: string;
}

/** GET /storage/upload-context (any authenticated user) — what an upload seam
 * needs BEFORE uploading: whether to pop the storage prompt (a user-choice rule
 * is active AND there's a real choice) and the hosts to offer. */
export interface UploadContext {
  /** Rule that captures these files before the ask (no prompt shown). */
  preempted_by?: string | null;
  ask_user: boolean;
  options: UploadOption[];
}

/** Lifecycle of a host-to-host move job (spec 102). */
export const MoveJobState = {
  pending: "pending",
  running: "running",
  done: "done",
  doneWithFailures: "done_with_failures",
  failed: "failed",
  canceled: "canceled",
} as const;
export type MoveJobStateValue = (typeof MoveJobState)[keyof typeof MoveJobState];

/** One file the move couldn't complete — the job keeps going past it. */
export interface MoveJobProblem {
  attachment_id: string;
  filename: string;
  detail: string;
}

/** POST /storage/hosts/{id}/move + GET /storage/move-jobs[/{id}]. */
export interface MoveJobRead {
  id: string;
  source_host_id: string;
  target_host_id: string;
  state: MoveJobStateValue;
  total: number;
  moved: number;
  failed: number;
  problems: MoveJobProblem[];
}
