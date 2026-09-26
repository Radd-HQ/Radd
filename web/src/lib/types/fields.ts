/** Fields registry + screens (field-layout config per project + issue type). */
// ---------------------------------------------------------------------------
// Screens (field-layout config per project + issue type)
// ---------------------------------------------------------------------------

/** Where a field sits in the issue view. secondary = shown but collapsed by
 * default in the compact peek panel; hidden = never rendered. */
export const ScreenPlacement = {
  primary: "primary",
  secondary: "secondary",
  hidden: "hidden",
} as const;
export type ScreenPlacementValue = (typeof ScreenPlacement)[keyof typeof ScreenPlacement];

/** One resolved field placement (`GET /screens/effective`), in render order.
 * `field` is a builtin token (assignee/cycle/labels/…) or `cf:<key>`. */
export interface EffectiveFieldRow {
  field: string;
  placement: ScreenPlacementValue;
  custom: boolean;
}

export interface EffectiveScreen {
  project_id: string;
  issue_type_id: string | null;
  source: "issue_type" | "project" | "default";
  fields: EffectiveFieldRow[];
}

