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

/** One role grant to a user or team; project_id null = global, set = that project. */
export interface RoleGrant {
  id: string;
  role_id: string;
  user_id: string | null;
  team_id: string | null;
  project_id: string | null;
}

/** POST /role-grants — grant a role to a subject at global (empty project_ids) or
 * project scope (one grant per project). */
export interface RoleGrantCreate {
  role_id: string;
  user_id?: string | null;
  team_id?: string | null;
  project_ids?: string[];
}
