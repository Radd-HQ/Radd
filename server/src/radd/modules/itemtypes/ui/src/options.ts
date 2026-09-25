import { api, optionContribution, type DirectoryOption } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "issue-types", noun: "issue types",
    meta: { entities: ["project", "role"] },
    fetch: ({ q, limit, offset, scope, signal }) => api.getPaged<DirectoryOption>("/issue-types/options", {
      signal, query: { ...scope, q, limit: String(limit), offset: String(offset) },
    }),
    resolve: ({ value, scope, signal }) => api.get<DirectoryOption[]>("/issue-types/options", {
      signal, query: { ...scope, value, limit: "1" },
    }),
  }),
];
