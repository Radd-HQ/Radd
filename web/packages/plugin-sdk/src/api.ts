/**
 * The typed fetch client a plugin uses to reach the Radd API — the same contract as the host's
 * client (base `/api/v1`, `credentials: include` so the session cookie flows, JSON in/out). A
 * remote consumes this from `@radd/plugin-sdk` (a singleton); it never re-implements auth/session.
 */

const API_BASE = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface Paged<T> { rows: T[]; total: number | null }

export interface RequestOptions {
  /** Select the generic paged response envelope, including the total header. */
  response?: "json" | "paged";
  method?: string;
  signal?: AbortSignal;
  keepalive?: boolean;
  body?: unknown;
  query?: Record<string, string | undefined>;
  /** When true, a 401 rejects instead of redirecting to /login (default redirects). */
  throwOn401?: boolean;
}

type Transport = <T>(path: string, options: RequestOptions) => Promise<T>;
let hostTransport: Transport | undefined;
let hostErrorMessage: ((error: unknown) => string) | undefined;
/** Share the host's session cancellation and error semantics; features never provide this. */
export function provideApiTransport(transport: Transport, formatError?: (error: unknown) => string): void {
  hostTransport = transport;
  hostErrorMessage = formatError;
}
export function errorMessage(error: unknown): string {
  return hostErrorMessage ? hostErrorMessage(error) : error instanceof Error ? error.message : String(error);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (hostTransport) return hostTransport<T>(path, options);
  const { method = "GET", body, query, throwOn401 = false } = options;
  const url = new URL(API_BASE + path, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, value);
    }
  }
  const response = await fetch(url, {
    method,
    credentials: "include",
    signal: options.signal,
    keepalive: options.keepalive,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    // A visitor (`__RADD_ANONYMOUS__`, spec 121) meets 401 as a refusal, not a lost session: no bounce to sign-in.
    const anonymous = (globalThis as { __RADD_ANONYMOUS__?: boolean }).__RADD_ANONYMOUS__ === true;
    if (response.status === 401 && !throwOn401 && !anonymous && window.location.pathname !== "/login") {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
    let detail: unknown = null;
    try {
      detail = await response.json();
      if (detail && typeof detail === "object" && "detail" in detail) {
        detail = (detail as { detail: unknown }).detail;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json();
  if (options.response === "paged") {
    const total = response.headers.get("X-Total-Count");
    return { rows: data, total: total === null ? null : Number(total) } as T;
  }
  return data as T;
}

export const api = {
  getPaged: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body" | "response">) =>
    request<Paged<T>>(path, { ...opts, method: "GET", response: "paged" }),
  get: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body" | "response">) =>
    request<T>(path, { ...opts, method: "GET" }),
  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body" | "response">) =>
    request<T>(path, { ...opts, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body" | "response">) =>
    request<T>(path, { ...opts, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body" | "response">) =>
    request<T>(path, { ...opts, method: "PUT", body }),
  delete: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body" | "response">) =>
    request<T>(path, { ...opts, method: "DELETE" }),
};

export { API_BASE };
