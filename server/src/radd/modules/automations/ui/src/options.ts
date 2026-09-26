/** Explicit option contracts consumed by Automations. Each provider owns its control and transport. */
export const OptionResource = {state: "states", release: "releases", issueType: "issue-types", form: "forms", user: "users", team: "teams", space: "page-spaces"} as const;
export type OptionResourceValue = typeof OptionResource[keyof typeof OptionResource];
