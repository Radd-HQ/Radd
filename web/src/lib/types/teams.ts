/** Teams, their directory-group reconcile, and global grants (specs 84/87). The directory
 * import vocabulary is the ldap plugin's own (RADD-1381). */

/** One instance-wide role grant (spec 87): exactly one of user_id/team_id.
 * Roles otherwise only attach to projects, which is why every global-scope atom
 * was ungrantable to a non-admin before this existed. */
export interface GlobalGrant {
  id: string;
  role_id: string;
  user_id: string | null;
  team_id: string | null;
  /** A directory group holding the role instance-wide (RADD-832). */
  group_id: string | null;
}

/** GET /teams (spec 01; ownership — spec 87). RADD-829 retired the directory
 * link: a team is always local, and reaches the directory by holding a GROUP
 * as a member (see RaddGroup / TeamGroup). */
export interface Team {
  id: string;
  name: string;
  created_at: string;
  owner_id: string | null;
  managers: string[];
  /** Resolved server-side: owner ∪ manager ∪ global-atom holder. The client
   * never re-derives it — per-team delegation isn't visible in the permission union. */
  can_manage: boolean;
  can_delete: boolean;
}

export interface TeamCreate {
  name: string;
  owner_id?: string;
}

/** PUT /teams/{id}/managers (spec 87) — full replace, owner-gated. */
export interface TeamManagersUpdate {
  user_ids: string[];
}

/** GET /teams/{id}/members (RADD-829): direct rows plus group-carried people —
 * `via_group` names the carrier (null = a direct user row). */
export interface TeamMember {
  user_id: string;
  email: string;
  name: string;
  via_group: string | null;
}

/** One mirrored directory group — GET /groups (RADD-829). */
export interface RaddGroup {
  id: string;
  dn: string;
  name: string;
  directory_missing_since: string | null;
  direct_member_count: number;
  /** RADD-833: what a grant on this group RESOLVES to (nesting included). */
  transitive_member_count?: number;
  parent_names?: string[];
  child_names?: string[];
}

/** GET /groups/{id}/reach — how many people a grant on the group resolves to,
 * nesting included (RADD-832). The guardrail number shown before a grant saves. */
export interface GroupReach {
  group_id: string;
  user_count: number;
}

/** A GROUP member of a team — GET /teams/{id}/groups (RADD-829). */
export interface TeamGroup {
  group_id: string;
  name: string;
  dn: string;
  directory_missing_since: string | null;
}

/** POST /teams/{id}/directory-sync (spec 84) — what the reconcile changed. */
export interface DirectorySyncResult {
  added: number;
  removed: number;
}
