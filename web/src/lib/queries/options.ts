/** Lean owner-provided names/references; each endpoint filters permissions first. */
import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import { queryKeys } from "./shared";

export const OptionResource = { state: "states", release: "releases", issueType: "issue-types", form: "forms", user: "users", team: "teams", role: "roles", space: "page-spaces", person: "users/directory", teamReference: "teams/directory", group: "groups", assignableRole: "roles/assignable" } as const;
export type OptionResourceValue = typeof OptionResource[keyof typeof OptionResource];
export interface DirectoryOption { value: string; label: string; hint: string }
export const OPTIONS_PAGE_SIZE = 50;
const tags = {
  [OptionResource.state]: Entity.project,
  [OptionResource.release]: Entity.release,
  [OptionResource.issueType]: Entity.project,
  [OptionResource.form]: Entity.form,
  [OptionResource.user]: Entity.member,
  [OptionResource.team]: Entity.team,
  [OptionResource.role]: Entity.role,
  [OptionResource.space]: Entity.docSpace,
  [OptionResource.person]: Entity.member,
  [OptionResource.teamReference]: Entity.team,
  [OptionResource.group]: Entity.group,
  [OptionResource.assignableRole]: Entity.role,
};
const optionMeta = (resource: OptionResourceValue) => resource === OptionResource.team || resource === OptionResource.teamReference
  ? entityMeta(Entity.team, Entity.project, Entity.role, Entity.member, Entity.group)
  : entityMeta(tags[resource], Entity.project, Entity.role);
export const optionsPageQuery = (resource: OptionResourceValue, q = "", page = 0, scope: Record<string, string> = {}) => queryOptions({
  queryKey: [...queryKeys.optionsPage(resource, q.trim(), page), scope],
  meta: optionMeta(resource),
  queryFn: ({ signal }) => api.getPaged<DirectoryOption>(`/${resource}/options`, { signal, query: {
    ...scope, q: q.trim(), limit: String(OPTIONS_PAGE_SIZE), offset: String(page * OPTIONS_PAGE_SIZE),
  } }),
});
export const optionByValueQuery = (resource: OptionResourceValue, value: string) => queryOptions({
  queryKey: queryKeys.optionByValue(resource, value),
  meta: optionMeta(resource),
  queryFn: ({ signal }) => api.get<DirectoryOption[]>(`/${resource}/options`, { signal, query: { value, limit: "1" } }),
  enabled: Boolean(value),
});
