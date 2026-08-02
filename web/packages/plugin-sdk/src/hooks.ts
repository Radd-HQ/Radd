import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./api";
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

/** Global + project permission checks off the current user / a project's `permissions`. */
export function usePermissions(): Permissions {
  const me = useCurrentUser();
  // Instance admins hold everything; the flat `permissions` array is the global union.
  const isAdmin = (me?.instance_role ?? ANONYMOUS_ROLE) === "admin";
  const globalSet = new Set<PermissionValue>(me?.permissions ?? []);
  return {
    global: (atom) => isAdmin || globalSet.has(atom),
    project: (project, atom) =>
      isAdmin || (project.permissions ?? []).includes(atom) || globalSet.has(atom),
  };
}

export function useCapabilities(): CapabilitiesManifest | undefined {
  const { data } = useQuery({
    queryKey: ["radd-sdk", "capabilities"],
    queryFn: () => api.get<CapabilitiesManifest>("/capabilities"),
    staleTime: 60_000,
  });
  return data;
}

/** True when a plugin is currently enabled (its UI should show). */
export function useHasPlugin(name: string): boolean {
  const caps = useCapabilities();
  // Absent manifest (still loading / anonymous) → optimistic true, matching the host's band-aid.
  return caps?.plugins?.includes(name) ?? true;
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
