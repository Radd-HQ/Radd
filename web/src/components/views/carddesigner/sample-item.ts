import {
  ItemKind,
  Priority,
  StateCategory,
  CycleStatus,
  ReleaseStatus,
  FieldType,
  SlaKind,
  type FieldDef,
  type Item,
  type ItemRollup,
  type ItemTimelogBatchEntry,
  type SlaBatchTimer,
} from "../../../lib/types";

/**
 * The designer preview's stand-in card data (spec 109): every builtin
 * attribute populated so a placed cell always shows SOMETHING. Custom-field
 * values are synthesized per field type on demand.
 */

export const SAMPLE_ITEM: Item = {
  id: "sample-item",
  project_id: "sample-project",
  key: "DEMO-128",
  number: 128,
  kind: ItemKind.epic, // epic so the progress cell has something to show
  title: "Design the onboarding flow for external requesters",
  description: "",
  state: { id: "sample-state", name: "In Progress", category: StateCategory.in_progress },
  priority: Priority.high,
  labels: ["design", "onboarding", "q3", "requesters"],
  parent: { id: "sample-parent", key: "DEMO-90", title: "Requester experience" },
  assignee: { id: "sample-assignee", name: "Alex Vega" },
  reporter: { id: "sample-reporter", name: "Sam Rivers" },
  team: { id: "sample-team", name: "Product" },
  child_count: 5,
  comment_count: 3,
  start_date: "2026-07-14",
  target_date: "2026-08-08",
  cycle: { id: "sample-cycle", name: "Cycle 12", status: CycleStatus.active },
  release: { id: "sample-release", version: "2.4.0", status: ReleaseStatus.planned },
  flagged: false,
  starred: false,
  estimate_points: 8,
  custom_fields: {},
  created_at: "2026-07-01T09:00:00Z",
  updated_at: "2026-07-29T15:30:00Z",
};

export const SAMPLE_ROLLUP: ItemRollup = {
  total: 5,
  done: 2,
  in_progress: 2,
  points_total: 21,
  points_done: 8,
  estimate_seconds: 12 * 3600,
  logged_seconds: 7 * 3600,
};

export const SAMPLE_TIMELOG: ItemTimelogBatchEntry = {
  logged_seconds: 5 * 3600 + 20 * 60,
  estimate_seconds: 8 * 3600,
};

/** One healthy response timer so a placed SLA cell shows a real chip. */
export const SAMPLE_SLA: SlaBatchTimer[] = [
  {
    policy_name: "Standard support",
    kind: SlaKind.response,
    due_at: "2026-08-01T17:00:00Z",
    met_at: null,
    breached: false,
    paused: false,
    remaining_seconds: 4 * 3600,
  },
];

/** A plausible value for a custom field, keyed by its type — select fields
 * use their first real option so chips carry genuine text. */
export function sampleCustomValue(field: FieldDef): string | number | boolean | string[] {
  switch (field.type) {
    case FieldType.boolean:
      return true;
    case FieldType.number:
      return 42;
    case FieldType.duration:
      return 90; // minutes
    case FieldType.date:
      return "2026-08-01";
    case FieldType.select:
      return field.options?.[0] ?? "Option A";
    case FieldType.multi_select:
      return field.options?.slice(0, 2) ?? ["One", "Two"];
    case FieldType.user:
      return "sample-assignee";
    case FieldType.url:
      return "https://example.com";
    default:
      return "Sample text";
  }
}
