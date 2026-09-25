export const projectQueryKeys = {
  projects: ["projects"] as const,
  firstProject: ["projects", "first"] as const,
  projectSummary: ["projects", "summary"] as const,
  projectById: (id: string) => ["projects", "id", id] as const,
  projectByKey: (key: string) => ["projects", "key", key.toUpperCase()] as const,
  projectsPage: (q: string, page: number, hideRelated: boolean, permission: string) =>
    ["projects", "page", { q, page, hideRelated, permission }] as const,
};
