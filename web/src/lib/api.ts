import { API_BASE, On401, RoutePath, type On401Value } from "./constants";
import { FORBIDDEN_FALLBACK_MESSAGE, pushToast } from "./toast";
import type { Finding } from "./types/automations";

/**
 * Thin typed fetch wrapper for the Radd API.
 * - base `/api/v1` (Vite dev proxy forwards `/api` to the backend)
 * - `credentials: "include"` so the `radd_session` cookie flows
 * - 401 → redirect to /login unless the caller opts out (`on401: On401.throw`)
 * - 403 → global toast (RBAC surprises surface everywhere), then rethrow
 */

export class ApiError extends Error {
  readonly status: number;
  /** FastAPI error payload: string detail, or a 422 list of field errors. */
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | undefined>;
  on401?: On401Value;
}

async function rawRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const { method = "GET", body, query, on401 = On401.redirect } = options;

  const url = new URL(API_BASE + path, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, value);
    }
  }

  const response = await fetch(url, {
    method,
    credentials: "include",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    if (
      response.status === 401 &&
      on401 === On401.redirect &&
      window.location.pathname !== RoutePath.login
    ) {
      window.location.assign(RoutePath.login);
    }
    const detail = await errorDetail(response);
    if (response.status === 403) {
      pushToast(typeof detail === "string" && detail ? detail : FORBIDDEN_FALLBACK_MESSAGE);
    }
    throw new ApiError(response.status, detail);
  }

  return response;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await rawRequest(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Rows + the pre-pagination total from X-Total-Count (RADD-883). `total` is
 * null when the server didn't send the header — an unpaged request. */
export interface Paged<T> {
  rows: T[];
  total: number | null;
}

const TOTAL_COUNT_HEADER = "X-Total-Count";

async function pagedRequest<T>(
  path: string,
  options: Omit<RequestOptions, "method" | "body"> = {},
): Promise<Paged<T>> {
  const response = await rawRequest(path, options);
  const rows = (await response.json()) as T[];
  const header = response.headers.get(TOTAL_COUNT_HEADER);
  return { rows, total: header === null ? null : Number(header) };
}

async function errorDetail(response: Response): Promise<unknown> {
  try {
    const payload = (await response.json()) as {
      detail?: unknown;
      errors?: unknown;
      position?: unknown;
    };
    // The fields registry 422s as {detail: "...", errors: ["key: message", …]} —
    // keep the whole payload so callers can map errors per field.
    if (Array.isArray(payload.errors)) return payload;
    // SLQ parse errors 422 as {detail: "...", position: <offset>} (spec 10) —
    // keep the payload so lib/slq.ts can point at the offending spot.
    if (typeof payload.position === "number") return payload;
    // Intake validation 422s as {detail, findings: [{message, field}], mode}
    // (spec 119) — the third vocabulary. Kept whole so `validationFindings`
    // can split the field-addressed ones from the general ones.
    if (Array.isArray((payload as { findings?: unknown }).findings)) return payload;
    return payload.detail ?? payload;
  } catch {
    return response.statusText;
  }
}

/** Human-readable message from any thrown value, for inline error display. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") return error.detail;
    if (Array.isArray(error.detail)) {
      const first = error.detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg;
    }
    if (error.detail && typeof error.detail === "object") {
      const payload = error.detail as { detail?: unknown; errors?: unknown };
      // {detail, errors: [...]} payloads (field validation, workflow transition
      // guards — spec 61): the specific failures beat the generic headline.
      if (Array.isArray(payload.errors)) {
        const errors = payload.errors.filter((entry) => typeof entry === "string");
        if (errors.length > 0) return errors.join("; ");
      }
      if (typeof payload.detail === "string") return payload.detail;
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}

/**
 * Per-field messages from a fields-registry 422
 * (`{detail, errors: ["department: required", …]}`) keyed by field key.
 * Empty when the error has some other shape.
 */
export function customFieldErrors(error: unknown): Record<string, string> {
  const result: Record<string, string> = {};
  if (!(error instanceof ApiError) || !error.detail || typeof error.detail !== "object") {
    return result;
  }
  const { errors } = error.detail as { errors?: unknown };
  if (!Array.isArray(errors)) return result;
  for (const entry of errors) {
    if (typeof entry !== "string") continue;
    const separator = entry.indexOf(": ");
    if (separator > 0) {
      result[entry.slice(0, separator)] = entry.slice(separator + 2);
    }
  }
  return result;
}

/**
 * Intake-validation findings from a spec-119 422
 * (`{detail: "item validation failed", findings: [{message, field}], mode}`).
 * Empty for any other error shape.
 *
 * Separate from `customFieldErrors` even though both end up highlighting a
 * control, because the payloads are different contracts and conflating them is
 * how a client starts guessing: `errors` is a list of `"key: message"` strings
 * about values the API could not accept, and `findings` are objects about things
 * a person should go and fix, addressed at builtin fields as well as custom ones.
 */
export function validationFindings(error: unknown): Finding[] {
  if (!(error instanceof ApiError) || !error.detail || typeof error.detail !== "object") {
    return [];
  }
  const { findings } = error.detail as { findings?: unknown };
  if (!Array.isArray(findings)) return [];
  return findings.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const row = entry as { message?: unknown; field?: unknown; node_id?: unknown };
    if (typeof row.message !== "string" || !row.message) return [];
    return [
      {
        message: row.message,
        field: typeof row.field === "string" ? row.field : "",
        node_id: typeof row.node_id === "string" ? row.node_id : "",
      },
    ];
  });
}

/** Findings keyed by the control they name — the shape every form's per-field
 * error prop already takes. Findings with no field are not in here; they belong
 * in the panel, and silently dropping them would lose real advice. */
export function findingsByField(findings: Finding[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const finding of findings) {
    if (!finding.field) continue;
    // First one wins: two checks naming the same control both matter, and the
    // panel shows every finding regardless — the control just cannot hold two.
    if (!(finding.field in result)) result[finding.field] = finding.message;
  }
  return result;
}

/** Backend detail prefix for a field-grant write rejection (spec 07). */
const DENIED_FIELDS_PREFIX = "no permission to write custom fields: ";

/**
 * Field keys named by a fields-grant 403
 * (`"no permission to write custom fields: a, b"`). Empty for any other error —
 * the client can't predict writability up front (grants + the user's subjects
 * aren't exposed), so denial is surfaced inline per field after the fact.
 */
export function deniedCustomFieldKeys(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 403) return [];
  const detail = errorMessage(error);
  if (!detail.startsWith(DENIED_FIELDS_PREFIX)) return [];
  return detail
    .slice(DENIED_FIELDS_PREFIX.length)
    .split(",")
    .map((key) => key.trim())
    .filter(Boolean);
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, options),
  /** GET a paged list: rows + the X-Total-Count total (null when unpaged). */
  getPaged: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    pagedRequest<T>(path, options),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "PUT", body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  // DELETE accepts an optional JSON body — TOTP disable (spec 48) requires a
  // current code in the body so a hijacked session can't silently strip MFA.
  delete: <T>(path: string, options?: Omit<RequestOptions, "method">) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
