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
    if (response.status === 401 && !throwOn401 && window.location.pathname !== "/login") {
      window.location.assign("/login");
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
