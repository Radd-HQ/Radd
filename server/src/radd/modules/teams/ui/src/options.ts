import { api, optionContribution, type DirectoryOption } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "teams", noun: "team names",
    meta: { entities: ["team", "project", "role", "member", "group"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/teams/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/teams/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
  optionContribution({
    resource: "teams/directory", noun: "teams",
    meta: { entities: ["team", "project", "role", "member", "group"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/teams/directory/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/teams/directory/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
];
