/** Issue link types (spec 91 — user-definable, scopeable). */
// ---------------------------------------------------------------------------
// Issue link types (spec 91 — user-definable, scopeable)
// ---------------------------------------------------------------------------

export const LinkDirection = {
  directed: "directed", // outward ≠ inward ("blocks" / "is blocked by")
  symmetric: "symmetric", // one name both ways ("relates to")
} as const;
export type LinkDirectionValue = (typeof LinkDirection)[keyof typeof LinkDirection];

export interface LinkTypeDef {
  id: string;
  key: string;
  name: string;
  outward_name: string;
  inward_name: string;
  direction: LinkDirectionValue;
  system: boolean;
  auto_managed: boolean;
  /** Empty = global; otherwise the projects this type is offered in. */
  project_ids: string[];
  usages: number;
  created_at: string;
}

export interface LinkTypeCreate {
  key: string;
  name: string;
  outward_name: string;
  inward_name?: string;
  direction?: LinkDirectionValue;
  project_ids?: string[];
}

export interface LinkTypeUpdate {
  name?: string;
  outward_name?: string;
  inward_name?: string;
  direction?: LinkDirectionValue;
  project_ids?: string[];
}
