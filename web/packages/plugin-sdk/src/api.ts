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

interface RequestOptions {
  method?: string;
  signal?: AbortSignal;
  body?: unknown;
  query?: Record<string, string | undefined>;
  /** When true, a 401 rejects instead of redirecting to /login (default redirects). */
  throwOn401?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
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
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    // Spec 121: while the host runs the shell for an anonymous visitor
    // (`globalThis.__RADD_ANONYMOUS__`, set by the host's auth state), a 401 is
    // an ordinary refusal — a surface the visitor cannot use — never a lost
    // session, so a plugin remote must not bounce the page to sign-in.
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
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "GET" }),
  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "PUT", body }),
  delete: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "DELETE" }),
};

export { API_BASE };
