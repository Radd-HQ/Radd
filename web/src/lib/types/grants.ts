/** Generic access grants (spec 92) + scopeable role grants (spec 91). */
// ---------------------------------------------------------------------------
// Generic access grants (spec 92 — one scopeable ACL primitive for any resource)
// ---------------------------------------------------------------------------

export const GrantSubject = { user: "user", team: "team", role: "role", group: "group" } as const;
export type GrantSubjectValue = (typeof GrantSubject)[keyof typeof GrantSubject];

/** One access grant: subject → access on a resource, scoped to a project (null = global). */
export interface AccessGrant {
  id: string;
  resource_type: string;
  resource_id: string;
  subject_type: GrantSubjectValue;
  subject_id: string;
  access: string;
  /** RADD-819: "allow" (default) | "deny" — deny wins on ties, specificity first. */
  effect: "allow" | "deny";
  project_id: string | null;
  /** RADD-820: null = permanent; expired rows never load into resolution. */
  expires_at?: string | null;
  granted_by?: string | null;
  created_at: string;
}

/**
 * `GET /grants/resources` — one registered resource's access MODEL (RADD-947).
 *
 * The mirror of the server's `ResourceSpec`, and the reason the editor no longer
 * takes these as per-call-site props: the registry that answers this is the same
 * one the write path validates against, so the form cannot offer a combination
 * the server refuses.
 */
export interface GrantResourceSpec {
  resource_type: string;
  label: string;
  accesses: string[];
  subjects: GrantSubjectValue[];
  /** false ⇒ grants carry no project scope; the editor shows no ScopePicker. */
  project_scoped: boolean;
  /** Ordered levels (viewer<editor<owner) vs independent flags (read/write). */
  hierarchical: boolean;
  /** No grants = open (fields, pages) or closed (views). */
  default_open: boolean;
}

/** POST /grants — global (empty project_ids) or one grant per project. */
export interface AccessGrantCreate {
  resource_type: string;
  resource_id: string;
  subject_type: GrantSubjectValue;
  subject_id: string;
  access: string;
  effect?: "allow" | "deny";
  /** RADD-820: ISO datetime; omitted = permanent. */
  expires_at?: string | null;
  project_ids?: string[];
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
  /** A directory group holding the role (RADD-832), resolved through nesting. */
  group_id: string | null;
  project_id: string | null;
  space_id: string | null;
}

/** POST /role-grants — grant a role to a subject instance-wide (no ids), on
 * projects, or in wiki spaces (one grant per id). */
export interface RoleGrantCreate {
  role_id: string;
  user_id?: string | null;
  team_id?: string | null;
  group_id?: string | null;
  /** Each id = one project-scoped grant. */
  project_ids?: string[];
  /** Each id = one SPACE-scoped grant (RADD-791). Both empty = one global grant. */
  space_ids?: string[];
}
