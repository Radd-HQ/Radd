/** Public Projects wire contract; permission atoms are extensible strings. */
export interface Project {
  id: string;
  key: string;
  name: string;
  /** RADD-1009: plain text, "" when never described. */
  description: string;
  created_at: string;
  /** The CURRENT user's effective permissions in this project (spec 06). */
  permissions: string[];
  /** RADD-1041 — why this row appears in a `GET /projects` listing: "entitled"
   * (held by grant) or "related" (their own work made it visible, e.g. a
   * ticket they filed). `null` on `POST /projects`'s response. Presentation
   * only — never used to decide access, only to decide what the sidebar's
   * "related projects" preference hides from the rail. */
  via?: "entitled" | "related" | null;
  /** Spec 121: the Public role is granted to Anyone on this project — its
   * public issues are readable without signing in. Derived from the grant. */
  public?: boolean;
  /** Spec 121: the Contributor role is granted to Signed-in users here. */
  contributions?: boolean;
}

export interface ProjectSummary {
  total: number;
  related_count: number;
  permissions: string[];
}
