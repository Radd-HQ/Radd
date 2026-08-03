/** Generic access grants (spec 92) + scopeable role grants (spec 91). */
// ---------------------------------------------------------------------------
// Generic access grants (spec 92 — one scopeable ACL primitive for any resource)
// ---------------------------------------------------------------------------

export const GrantSubject = { user: "user", team: "team", role: "role" } as const;
export type GrantSubjectValue = (typeof GrantSubject)[keyof typeof GrantSubject];

/** One access grant: subject → access on a resource, scoped to a project (null = global). */
export interface AccessGrant {
  id: string;
  resource_type: string;
  resource_id: string;
  subject_type: GrantSubjectValue;
  subject_id: string;
  access: string;
  project_id: string | null;
  created_at: string;
}

/** POST /grants — global (empty project_ids) or one grant per project. */
export interface AccessGrantCreate {
  resource_type: string;
  resource_id: string;
  subject_type: GrantSubjectValue;
  subject_id: string;
  access: string;
  project_ids?: string[];
}

/** GET /grants/resources — a registered resource's grant model, for the GrantsEditor. */
export interface ResourceGrantSpec {
  resource_type: string;
  label: string;
  accesses: string[];
  subjects: GrantSubjectValue[];
  project_scoped: boolean;
  hierarchical: boolean;
  default_open: boolean;
}

// ---------------------------------------------------------------------------
// Scopeable role grants (spec 91 — the unified Grant Role dialog)
// ---------------------------------------------------------------------------

/** One role grant to a user or team. Both scope ids null = instance-wide; one
 *  set = that project, or that wiki space (RADD-791). Never both. */
export interface RoleGrant {
  id: string;
  role_id: string;
  user_id: string | null;
  team_id: string | null;
  project_id: string | null;
  space_id: string | null;
}

/** POST /role-grants — grant a role to a subject instance-wide (no ids), on
 * projects, or in wiki spaces (one grant per id). */
export interface RoleGrantCreate {
  role_id: string;
  user_id?: string | null;
  team_id?: string | null;
  /** Each id = one project-scoped grant. */
  project_ids?: string[];
  /** Each id = one SPACE-scoped grant (RADD-791). Both empty = one global grant. */
  space_ids?: string[];
}
