import { api, optionContribution, type DirectoryOption } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "states", noun: "state names",
    meta: { entities: ["project", "role"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/states/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/states/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
];
