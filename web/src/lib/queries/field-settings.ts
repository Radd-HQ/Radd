/** Bounded field settings reads; the legacy registry remains complete for item consumers. */
import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import type { FieldDef } from "../types";
import type { DirectoryOption } from "./options";
import { queryKeys } from "./shared";

export const FIELD_DIRECTORY_PAGE_SIZE = 50;
export type FieldScopePermission = "field.create" | "field.update" | "field.manage";
export interface FieldSummary { id: string; key: string; name: string; type: FieldDef["type"]; project_count: number; restricted: boolean }
export interface ManagedField extends FieldDef { can_update: boolean; can_delete: boolean; can_manage: boolean; option_count: number }
export interface FieldSettingsSummary { can_access: boolean; can_create: boolean; can_create_global: boolean; can_update_global: boolean; can_manage_builtin: boolean; can_manage_builtin_projects: boolean }
const meta = entityMeta(Entity.field, Entity.project, Entity.role, Entity.member, Entity.team, Entity.group, Entity.accessGrant);
export const fieldSettingsSummaryQuery = () => queryOptions({
  queryKey: [...queryKeys.fields, "settings-summary"] as const, meta,
  queryFn: ({ signal }) => api.get<FieldSettingsSummary>("/fields/settings-summary", { signal }),
});
export const fieldDirectoryQuery = (q: string, page: number) => queryOptions({
  queryKey: [...queryKeys.fields, "directory", q, page] as const, meta,
  queryFn: ({ signal }) => api.getPaged<FieldSummary>("/fields/directory", { signal, query: { q, limit: String(FIELD_DIRECTORY_PAGE_SIZE), offset: String(page * FIELD_DIRECTORY_PAGE_SIZE) } }),
});
export const managedFieldQuery = (id: string) => queryOptions({
  queryKey: [...queryKeys.fields, "definition", id] as const, meta, enabled: Boolean(id),
  queryFn: ({ signal }) => api.get<ManagedField>(`/fields/definitions/${id}`, { signal, query: { include_options: "false" } }),
});
export const fieldProjectChoicesQuery = (permission: FieldScopePermission, q: string, page: number) => queryOptions({
  queryKey: [...queryKeys.fields, "scope-projects", permission, q, page] as const, meta,
  queryFn: ({ signal }) => api.getPaged<DirectoryOption>("/fields/scope-projects/options", { signal, query: { permission, q, limit: String(FIELD_DIRECTORY_PAGE_SIZE), offset: String(page * FIELD_DIRECTORY_PAGE_SIZE) } }),
});
export const fieldProjectReferencesQuery = (ids: string[]) => {
  const identifiers = [...new Set(ids)].sort();
  return queryOptions({
    queryKey: [...queryKeys.fields, "scope-references", identifiers] as const, meta, enabled: identifiers.length > 0,
    queryFn: ({ signal }) => api.post<DirectoryOption[]>("/fields/scope-projects/references", { ids: identifiers }, { signal }),
  });
};

/** Catalog order is stable; exclusion and search are applied before the SQL window. */
export const fieldOptionsQuery = (id: string, q: string, page: number, exclude?: string) => queryOptions({
  queryKey: [...queryKeys.fields, "definition", id, "options", q, page, exclude ?? null] as const, meta,
  queryFn: ({ signal }) => api.getPaged<string>(`/fields/definitions/${id}/options`, {
    signal, query: { q, limit: String(FIELD_DIRECTORY_PAGE_SIZE), offset: String(page * FIELD_DIRECTORY_PAGE_SIZE), ...(exclude !== undefined ? { exclude } : {}) },
  }),
});
