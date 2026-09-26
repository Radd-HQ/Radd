/** Settings → AI: the provider registry's wire shapes, endpoints and cache tags. */

/** Wire protocol a provider speaks. */
export const AiWireShape = {
  openai: "openai",
  anthropic: "anthropic",
  // The built-in CPU embedding backend — embeddings role only.
  local: "local",
} as const;
export type AiWireShapeValue = (typeof AiWireShape)[keyof typeof AiWireShape];

/** Where a provider row came from — env-seeded rows are ordinary editable rows. */
export const AiProviderSource = { env: "env", user: "user" } as const;
type AiProviderSourceValue = (typeof AiProviderSource)[keyof typeof AiProviderSource];

/** What a configured model is FOR — features resolve a role, never a provider. */
export const AiRole = { chat: "chat", embeddings: "embeddings", vision: "vision" } as const;
export type AiRoleValue = (typeof AiRole)[keyof typeof AiRole];

/** One provider row from GET /ai/providers — the api key never leaves the server. */
export interface AiProviderRead {
  id: string;
  name: string;
  wire_shape: AiWireShapeValue;
  /** "" = the wire shape's default endpoint. */
  base_url: string;
  has_api_key: boolean;
  default_model: string;
  source: AiProviderSourceValue;
  /** RADD-1273: off = Radd asks a thinking model not to think (the default); on = the model's own default. */
  reasoning: boolean;
  /** Admin-supplied JSON object merged LAST into every chat payload. */
  request_params: Record<string, unknown>;
}

/** POST /ai/providers body; PATCH sends the same shape ("" api_key = keep the stored key). */
export interface AiProviderPayload {
  name: string;
  wire_shape: AiWireShapeValue;
  base_url?: string;
  api_key?: string;
  default_model?: string;
  reasoning?: boolean;
  request_params?: Record<string, unknown>;
}

/** One role assignment from GET /ai/roles (unassigned roles have no row). */
export interface AiRoleRead {
  role: AiRoleValue;
  provider_id: string;
  provider_name: string;
  /** "" = fall back to the provider's default model. */
  model: string;
  effective_model: string;
}

/** POST /ai/providers/{id}/test — failures come back as data, never a 502. */
export interface AiProbeResult {
  ok: boolean;
  error: string;
  latency_ms: number | null;
}

/** One editor-action preset prompt (consumed by the editor's AI menu). */
export interface AiPreset {
  id: string;
  name: string;
  prompt: string;
  enabled: boolean;
  position: number;
}

export interface EmbeddingCoverage {
  enabled: boolean;
  items_total: number;
  items_embedded: number;
  docs_total: number;
  docs_embedded: number;
}

export interface LocalEmbedInfo {
  available: boolean;
  default_model: string;
  models: string[];
}

const id = (value: string) => encodeURIComponent(value);
export const AiPath = {
  providers: "/ai/providers",
  provider: (providerId: string) => `/ai/providers/${id(providerId)}`,
  providerTest: (providerId: string) => `/ai/providers/${id(providerId)}/test`,
  roles: "/ai/roles",
  role: (role: AiRoleValue) => `/ai/roles/${id(role)}`,
  presets: "/ai/presets",
  preset: (presetId: string) => `/ai/presets/${id(presetId)}`,
  localEmbed: "/ai/local-embed",
  coverage: "/ai/embeddings/coverage",
} as const;

/** Cache tags. `/ai/status` declares the provider and role tags, so one invalidation here refreshes
 *  this page's lists and every AI affordance's gate. */
export const AiEntity = { provider: "aiProvider", role: "aiRole", preset: "aiPreset" } as const;

/** Section headings on the page share one style. */
export const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";
