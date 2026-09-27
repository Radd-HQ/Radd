import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { capabilitiesQueryKey } from "./query-keys";
import { InstanceRole } from "./types";
import type {
  CapabilitiesManifest,
  Item,
  Me,
  Permissions,
  PermissionValue,
  Project,
} from "./types";

/**
 * Data hooks a plugin's UI uses (docs/plugin-platform.md §7.5 — the permission-aware data SDK,
 * frontend side). They read through the shared `@tanstack/react-query` client (a federation
 * singleton), so a plugin shares the host's cache and session. Keys are namespaced `radd-sdk:*`.
 */

const ANONYMOUS_ROLE = "";

export function useCurrentUser(): Me | null {
  const { data } = useQuery({
    queryKey: ["radd-sdk", "me"],
    queryFn: () => api.get<Me>("/auth/me", { throwOn401: true }).catch(() => null),
    staleTime: 60_000,
  });
  return data ?? null;
}

/** A signed-in account, not a visitor (spec 121: `/auth/me` answers a visitor as the Anyone
 *  principal, so `useCurrentUser()` alone does not say who can write). */
export function useIsAuthenticated(): boolean {
  const me = useCurrentUser();
  return Boolean(me && !me.anonymous);
}


/** `global_role` is what the server's bypass (authz.is_admin) answers for THIS credential, and what
 *  the host's own checker reads (RADD-1392). `instance_role` is only the account's column; a page
 *  gating on it can offer what its API refuses, or hide what it allows. */
function isInstanceAdmin(me: Me | null): boolean {
  return (me?.global_role ?? me?.instance_role ?? ANONYMOUS_ROLE) === InstanceRole.admin;
}

/** Whether the signed-in credential is an instance admin (false while `/auth/me` loads). */
export function useIsInstanceAdmin(): boolean {
  return isInstanceAdmin(useCurrentUser());
}

/** Global + project permission checks off the current user / a project's `permissions`. */
export function usePermissions(): Permissions {
  const me = useCurrentUser();
  // Instance admins hold everything; the flat `permissions` array is the global union.
  const isAdmin = isInstanceAdmin(me);
  const globalSet = new Set<PermissionValue>(me?.permissions ?? []);
  return {
    global: (atom) => isAdmin || globalSet.has(atom),
    project: (project, atom) =>
      isAdmin || (project.permissions ?? []).includes(atom) || globalSet.has(atom),
  };
}

/** The manifest changes when a plugin is toggled; the shell polls it, so a page may hold it a minute. */
const CAPABILITIES_STALE_MS = 60_000;

/** The manifest query itself (`GET /capabilities`), shared with the host under the same key — for
 *  a page that must SAY when the read failed and offer a retry (RADD-1459), rather than spin on
 *  `undefined` forever. Most pages want `useCapabilities()`. */
export function useCapabilitiesQuery() {
  return useQuery({
    queryKey: capabilitiesQueryKey,
    queryFn: () => api.get<CapabilitiesManifest>("/capabilities"),
    staleTime: CAPABILITIES_STALE_MS,
  });
}

export function useCapabilities(): CapabilitiesManifest | undefined {
  return useCapabilitiesQuery().data;
}

/** True when a plugin is currently enabled (its UI should show). */
export function useHasPlugin(name: string): boolean {
  const caps = useCapabilities();
  // Loading is unavailable; consumers must never issue feature requests optimistically.
  return caps?.plugins?.includes(name) ?? false;
}

/** SLQ-scoped item list (GET /items?q=…) — permission-scoped by the backend. */
export function useItemsQuery(slq: string, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["radd-sdk", "items", slq],
    queryFn: () => api.get<{ items: Item[] }>("/items", { query: { q: slq || undefined } }),
    enabled: opts?.enabled ?? true,
  });
}

/** A single hydrated item (GET /items/{id}). */
export function useItemQuery(id: string | undefined) {
  return useQuery({
    queryKey: ["radd-sdk", "item", id],
    queryFn: () => api.get<Item>(`/items/${id}`),
    enabled: Boolean(id),
  });
}

/** The projects the current user can see (GET /projects). */
export function useProjectsQuery() {
  return useQuery({
    queryKey: ["radd-sdk", "projects"],
    queryFn: () => api.get<Project[]>("/projects"),
    staleTime: 30_000,
  });
}

/** The shared query client, for imperative invalidation from a plugin mutation. */
export function useApiQueryClient(): QueryClient {
  return useQueryClient();
}
