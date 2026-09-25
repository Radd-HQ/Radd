import { api, optionContribution, type DirectoryOption } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "users", noun: "people", hintAfter: true, stacked: true,
    meta: { entities: ["member", "project", "role"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/users/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/users/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
  optionContribution({
    resource: "users/directory", noun: "people",
    meta: { entities: ["member", "project", "role"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/users/directory/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/users/directory/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
  optionContribution({
    resource: "roles", noun: "roles",
    meta: { entities: ["role", "project"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/roles/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/roles/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
  optionContribution({
    resource: "roles/assignable", noun: "roles",
    meta: { entities: ["role", "project"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/roles/assignable/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/roles/assignable/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
];
