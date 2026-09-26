/** Public Projects wire contract; permission atoms are extensible strings. */
export interface Project {
  id: string;
  key: string;
  name: string;
  /** "" when never described. */
  description: string;
  created_at: string;
  /** The CURRENT user's effective permissions in this project. */
  permissions: string[];
  /** Why the row is listed: "entitled" (a grant) or "related" (own work made it visible). Presentation
   *  only, never used for access. */
  via?: "entitled" | "related" | null;
  /** Anyone holds the Public role here (spec 121; derived from the grant). */
  public?: boolean;
  /** Signed-in users hold the Contributor role here. */
  contributions?: boolean;
}

export interface ProjectSummary {
  total: number;
  related_count: number;
  permissions: string[];
}
