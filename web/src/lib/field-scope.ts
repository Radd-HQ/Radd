import type { FieldDef } from "./types";

/**
 * Whether a field applies to a project (spec 90 follow-up: multi-project scope).
 * A field with no scoped projects is GLOBAL (every project); otherwise it applies
 * only where its `project_ids` include the project. `projectId` null = the global
 * scope (admin surfaces) — only global fields qualify.
 */
export function fieldInScope(field: FieldDef, projectId: string | null): boolean {
  if (field.project_ids.length === 0) return true;
  return projectId !== null && field.project_ids.includes(projectId);
}
