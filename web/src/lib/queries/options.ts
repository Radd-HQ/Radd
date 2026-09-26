/** Legacy source-name aliases for host callers being migrated. No queries or provider metadata. */
export const OptionResource = { state: "states", release: "releases", issueType: "issue-types", form: "forms", user: "users", team: "teams", role: "roles", space: "page-spaces", person: "users/directory", teamReference: "teams/directory", group: "groups", assignableRole: "roles/assignable" } as const;
export type OptionResourceValue = typeof OptionResource[keyof typeof OptionResource];
