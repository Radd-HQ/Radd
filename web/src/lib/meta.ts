import {
  CircleCheck,
  CircleDashed,
  CircleDot,
  CircleSlash,
  CircleX,
  Diamond,
  FileCode,
  FileText,
  GitBranch,
  GitCommitHorizontal,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
  Link2,
  ListTree,
  OctagonAlert,
  Palette,
  Paperclip,
  SignalHigh,
  SignalLow,
  SignalMedium,
  type LucideIcon,
} from "lucide-react";
import { Globe, Lock, Users } from "lucide-react";
import {
  VcsProvider,
  VcsRefType,
  WebLinkCategory,
  type VcsProviderValue,
  type VcsRefTypeValue,
  type WebLinkCategoryValue,
  ItemVisibility,
  type ItemVisibilityValue,
} from "./types";
import {
  ActionType,
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  CommentVisibility,
  CycleStatus,
  FieldType,
  InstanceRole,
  ItemKind,
  ItemLinkType,
  Priority,
  ReleaseStatus,
  ReportInterval,
  StateCategory,
  ViewAxis,
  type ActionTypeValue,
  type BuiltinRuleField,
  type CommentVisibilityValue,
  type CycleStatusValue,
  type FieldTypeValue,
  type InstanceRoleValue,
  type ItemKindValue,
  type ItemLinkTypeValue,
  type PriorityValue,
  type ReleaseStatusValue,
  type ReportIntervalValue,
  type StateCategoryValue,
  type ViewAxisValue,
} from "./types";

/**
 * Display metadata for backend enums — the single place mapping enum members
 * to labels, icons, ordering, and accent classes. No component hardcodes these.
 */

export interface PriorityMeta {
  label: string;
  /** Compact mono tag form (board cards). */
  short: string;
  icon: LucideIcon;
  className: string;
  /** Sort weight, most urgent first. */
  order: number;
}

export const PRIORITY_META: Record<PriorityValue, PriorityMeta> = {
  [Priority.blocker]: { label: "Blocker", short: "BLOCK", icon: OctagonAlert, className: "text-red-400", order: 0 },
  [Priority.high]: { label: "High", short: "HIGH", icon: SignalHigh, className: "text-orange-400", order: 1 },
  [Priority.normal]: { label: "Normal", short: "NORM", icon: SignalMedium, className: "text-fg-secondary", order: 2 },
  [Priority.low]: { label: "Low", short: "LOW", icon: SignalLow, className: "text-fg-muted", order: 3 },
};

/** Spec 121 — who may read an issue. Labels differ by whether the project is
 * public: the `label` reads right in a public project, `privateLabel` in a
 * private one (where public and internal are the same audience). */
export interface VisibilityMeta {
  label: string;
  privateLabel: string;
  description: string;
  icon: LucideIcon;
}

export const VISIBILITY_META: Record<ItemVisibilityValue, VisibilityMeta> = {
  [ItemVisibility.public]: {
    label: "Public",
    privateLabel: "Normal",
    description: "Anyone who can read the project — the world, if the project is public.",
    icon: Globe,
  },
  [ItemVisibility.internal]: {
    label: "Members only",
    privateLabel: "Normal",
    description: "Members of the project. Hidden from the world even in a public project.",
    icon: Users,
  },
  [ItemVisibility.restricted]: {
    label: "Restricted",
    privateLabel: "Restricted",
    description: "Only the reporter, the assignee and participants.",
    icon: Lock,
  },
};

export const VISIBILITY_ORDER: readonly ItemVisibilityValue[] = [
  ItemVisibility.public,
  ItemVisibility.internal,
  ItemVisibility.restricted,
];

export const PRIORITY_ORDER: readonly PriorityValue[] = [
  Priority.blocker,
  Priority.high,
  Priority.normal,
  Priority.low,
];

/** Priority chip fills as `var()` references (RADD-875) — theme-scaled in
 * index.css beside `--chart-*`. The rail chip pairs them with the same
 * non-inverting dark glyph the roadmap category bars use. */
export const PRIORITY_FILLS: Record<PriorityValue, string> = {
  [Priority.blocker]: "var(--priority-blocker)",
  [Priority.high]: "var(--priority-high)",
  [Priority.normal]: "var(--priority-normal)",
  [Priority.low]: "var(--priority-low)",
};

export interface CategoryMeta {
  label: string;
  /** Dot/accent color for column headers and state selects. */
  dotClassName: string;
  /** Tinted pill (border/bg/text) for the state pill on rows and cards. */
  pillClassName: string;
  /** Board column ordering (states also carry `position` within a project). */
  order: number;
}

export const CATEGORY_META: Record<StateCategoryValue, CategoryMeta> = {
  [StateCategory.triage]: {
    label: "Triage",
    dotClassName: "bg-chart-triage",
    pillClassName: "border-chart-triage/40 bg-chart-triage/12 text-chart-triage-ink",
    order: 0,
  },
  [StateCategory.backlog]: {
    label: "Backlog",
    dotClassName: "bg-chart-backlog",
    pillClassName: "border-emphasis/60 bg-elevated/60 text-fg",
    order: 1,
  },
  [StateCategory.todo]: {
    label: "Todo",
    dotClassName: "bg-chart-todo",
    pillClassName: "border-chart-todo/40 bg-chart-todo/12 text-chart-todo-ink",
    order: 2,
  },
  [StateCategory.in_progress]: {
    label: "In Progress",
    dotClassName: "bg-chart-progress",
    pillClassName: "border-chart-progress/40 bg-chart-progress/12 text-chart-progress-ink",
    order: 3,
  },
  [StateCategory.done]: {
    label: "Done",
    dotClassName: "bg-chart-done",
    pillClassName: "border-strong bg-elevated/40 text-fg-muted",
    order: 4,
  },
  [StateCategory.canceled]: {
    label: "Canceled",
    dotClassName: "bg-chart-canceled",
    pillClassName: "border-strong bg-elevated/40 text-fg-muted",
    order: 5,
  },
};

export const CATEGORY_ORDER: readonly StateCategoryValue[] = [
  StateCategory.triage,
  StateCategory.backlog,
  StateCategory.todo,
  StateCategory.in_progress,
  StateCategory.done,
  StateCategory.canceled,
];

export interface KindMeta {
  label: string;
  icon: LucideIcon;
  className: string;
}

export const KIND_META: Record<ItemKindValue, KindMeta> = {
  [ItemKind.epic]: { label: "Epic", icon: Diamond, className: "text-purple-400" },
  [ItemKind.issue]: { label: "Issue", icon: CircleDot, className: "text-blue-400" },
  [ItemKind.subtask]: { label: "Subtask", icon: ListTree, className: "text-fg-secondary" },
};

export const KIND_ORDER: readonly ItemKindValue[] = [
  ItemKind.epic,
  ItemKind.issue,
  ItemKind.subtask,
];

/** Fallback icon for items created before the backend `kind` field landed. */
export const NO_KIND_ICON: LucideIcon = CircleDashed;

/** Plain-language labels for the workflow enforcement modes (spec 107):
 * Guarded = the transitions list adds checks to the moves it covers;
 * Strict = the list is the complete map of allowed moves. */
export const TRANSITION_MODE_LABELS: Record<string, string> = {
  off: "Off — anyone can move items to any state",
  guards: "Guarded — moves listed below must meet their conditions; other moves stay free",
  strict: "Strict — ONLY the moves listed below are possible, each meeting its conditions",
};

/** Friendly option labels for ENUMERATED scoped settings, per key — the
 * generic ScopedSettingsEditor renders these in its select (the server's
 * `choices` carries the wire values). */
export const SETTING_CHOICE_LABELS: Record<string, Record<string, string>> = {
  workflow_transition_mode: TRANSITION_MODE_LABELS,
};

/** Field-type display labels + form ordering (settings/fields, spec 04 Phase 3). */
export const FIELD_TYPE_LABELS: Record<FieldTypeValue, string> = {
  [FieldType.text]: "Text",
  [FieldType.number]: "Number",
  [FieldType.boolean]: "Boolean",
  [FieldType.date]: "Date",
  [FieldType.select]: "Select",
  [FieldType.multi_select]: "Multi-select",
  [FieldType.user]: "User",
  [FieldType.url]: "URL",
  [FieldType.duration]: "Duration",
};

export const FIELD_TYPE_ORDER: readonly FieldTypeValue[] = [
  FieldType.text,
  FieldType.number,
  FieldType.boolean,
  FieldType.date,
  FieldType.select,
  FieldType.multi_select,
  FieldType.user,
  FieldType.url,
  FieldType.duration,
];

/** Field types whose values come from a fixed options list. */
export function fieldTypeHasOptions(type: FieldTypeValue): boolean {
  return type === FieldType.select || type === FieldType.multi_select;
}

/** Display names of the builtin item fields that can carry access rules (spec 36). */
export const BUILTIN_FIELD_LABELS: Record<BuiltinRuleField, string> = {
  title: "Title",
  description: "Description",
  state: "State",
  priority: "Priority",
  assignee: "Assignee",
  reporter: "Reporter",
  team: "Team",
  labels: "Labels",
  parent: "Parent",
  start_date: "Start date",
  target_date: "Target date",
  cycle: "Cycle",
  release: "Release",
  flagged: "Flag",
  estimate_points: "Points",
};

/** The server-wide role ladder (spec 86): `users.instance_role`. */
export const INSTANCE_ROLE_LABELS: Record<InstanceRoleValue, string> = {
  [InstanceRole.member]: "Member",
  [InstanceRole.admin]: "Admin",
};

/** Builtin view-axis labels (custom-field axes are labeled from the registry). */
export const VIEW_AXIS_LABELS: Record<ViewAxisValue, string> = {
  [ViewAxis.state]: "State",
  [ViewAxis.stateCategory]: "State category",
  [ViewAxis.assignee]: "Assignee",
  [ViewAxis.priority]: "Priority",
  [ViewAxis.kind]: "Kind",
  [ViewAxis.team]: "Team",
  [ViewAxis.cycle]: "Cycle",
  [ViewAxis.epic]: "Epic",
};

export const VIEW_AXIS_ORDER: readonly ViewAxisValue[] = [
  ViewAxis.state,
  ViewAxis.stateCategory,
  ViewAxis.assignee,
  ViewAxis.priority,
  ViewAxis.kind,
  ViewAxis.team,
  ViewAxis.cycle,
  ViewAxis.epic,
];

/** Cycle status display metadata (spec 18) — status is derived from dates. */
export interface StatusMeta {
  label: string;
  /** Dot/accent color. */
  dotClassName: string;
  /** Tinted pill (border/bg/text) — set where statuses render as pills. */
  pillClassName?: string;
}

export const CYCLE_STATUS_META: Record<CycleStatusValue, StatusMeta> = {
  [CycleStatus.draft]: {
    label: "Draft",
    dotClassName: "bg-fg-secondary",
    pillClassName: "border-emphasis/60 bg-elevated/60 text-fg",
  },
  // Upcoming/active ride the workflow-state scale (RADD-900): a queued cycle
  // is the todo blue, a running one the progress green — the same traffic-light
  // reading as items, and the raw blue-200/emerald-200 shades they used had no
  // light remap (stock blue-200 on white is ~1.4:1).
  [CycleStatus.upcoming]: {
    label: "Upcoming",
    dotClassName: "bg-chart-todo",
    pillClassName: "border-chart-todo/40 bg-chart-todo/12 text-chart-todo-ink",
  },
  [CycleStatus.active]: {
    label: "Active",
    dotClassName: "bg-chart-progress",
    pillClassName: "border-chart-progress/40 bg-chart-progress/12 text-chart-progress-ink",
  },
  [CycleStatus.completed]: {
    label: "Completed",
    dotClassName: "bg-fg-faint",
    pillClassName: "border-strong bg-elevated/40 text-fg-muted",
  },
};

/**
 * Cycle-header ordering when grouping a view by cycle (spec 23): live work
 * first, staging next, finished last. Within a status, view-utils sorts by
 * start date (drafts, dateless, by name).
 */
export const CYCLE_STATUS_ORDER: readonly CycleStatusValue[] = [
  CycleStatus.active,
  CycleStatus.upcoming,
  CycleStatus.draft,
  CycleStatus.completed,
];

export const RELEASE_STATUS_META: Record<ReleaseStatusValue, StatusMeta> = {
  [ReleaseStatus.planned]: { label: "Planned", dotClassName: "bg-amber-400" },
  [ReleaseStatus.released]: { label: "Released", dotClassName: "bg-emerald-400" },
};

/**
 * Dependency-link section headings by type and direction (spec 18): outgoing =
 * this item is the source; incoming = this item is the target. `relates` is
 * symmetric, so both directions read the same.
 */
export const LINK_GROUP_LABELS: Record<
  ItemLinkTypeValue,
  { outgoing: string; incoming: string }
> = {
  [ItemLinkType.blocks]: { outgoing: "Blocks", incoming: "Blocked by" },
  [ItemLinkType.relates]: { outgoing: "Relates to", incoming: "Relates to" },
  [ItemLinkType.duplicates]: { outgoing: "Duplicates", incoming: "Duplicated by" },
  [ItemLinkType.mentions]: { outgoing: "References", incoming: "Referenced by" },
};

/**
 * State-category fills for inline-SVG charts (spec 19), as `var()` references
 * so they follow the theme like every other token. `dotClassName` above resolves
 * the SAME `--chart-*` variables through Tailwind utilities, so the dots, pills,
 * roadmap bars and report series are now genuinely one source — they used to be
 * palette classes on one side and loose hexes on the other, and had drifted.
 */
export const CATEGORY_CHART_COLORS: Record<StateCategoryValue, string> = {
  [StateCategory.triage]: "var(--chart-triage)",
  [StateCategory.backlog]: "var(--chart-backlog)",
  [StateCategory.todo]: "var(--chart-todo)",
  [StateCategory.in_progress]: "var(--chart-progress)",
  [StateCategory.done]: "var(--chart-done)",
  [StateCategory.canceled]: "var(--chart-canceled)",
};

/** Report bucket-interval labels + ordering for the throughput/CFD toggle (spec 19). */
export const REPORT_INTERVAL_LABELS: Record<ReportIntervalValue, string> = {
  [ReportInterval.day]: "Day",
  [ReportInterval.week]: "Week",
};

export const REPORT_INTERVAL_ORDER: readonly ReportIntervalValue[] = [
  ReportInterval.day,
  ReportInterval.week,
];

/** Burnup line colors (spec 19): scope vs completed. `var()` references like
 * CATEGORY_CHART_COLORS above — the charts were still drawing the retired
 * pre-Dusk indigo as hex, theme-blind (RADD-900). */
export const BURNUP_SCOPE_COLOR = "var(--accent-fill)";
export const BURNUP_COMPLETED_COLOR = "var(--status-success)";

/** Accent for single-series bar charts (throughput, velocity). */
export const CHART_ACCENT_COLOR = "var(--accent-fill)";

/** SLA trend colors (spec 63): targets met vs breached per week. */
export const SLA_MET_COLOR = "var(--status-success)";
export const SLA_BREACHED_COLOR = "var(--status-danger)";

// ---------------------------------------------------------------------------
// Automations + intake forms (spec 20)
// ---------------------------------------------------------------------------

/** Trigger display name: the catalog's label when known, else the raw event type.
 * (Trigger metadata lives server-side — GET /automations/catalog, spec 58.) */
export function triggerLabel(
  trigger: string,
  catalog: { triggers: { event_type: string; label: string }[] } | undefined,
): string {
  if (trigger === MANUAL_TRIGGER) return "Manual (editor / menu)";
  if (trigger === SCHEDULE_TRIGGER) return "On a schedule";
  return catalog?.triggers.find((t) => t.event_type === trigger)?.label ?? trigger;
}

/** Action-type labels for the rule builder's action-type select. */
export const ACTION_TYPE_LABELS: Record<ActionTypeValue, string> = {
  [ActionType.setState]: "Set state",
  [ActionType.setPriority]: "Set priority",
  [ActionType.setAssignee]: "Set assignee",
  [ActionType.assignRoundRobin]: "Assign next from team",
  [ActionType.setTeam]: "Set team",
  [ActionType.addLabel]: "Add label",
  [ActionType.removeLabel]: "Remove label",
  [ActionType.setCycle]: "Set cycle",
  [ActionType.setRelease]: "Set release",
  [ActionType.setCustomField]: "Set custom field",
  [ActionType.addComment]: "Add comment",
  [ActionType.setParent]: "Set parent",
  [ActionType.setType]: "Set issue type",
  [ActionType.setReporter]: "Set reporter",
  [ActionType.setDates]: "Set dates",
  [ActionType.setEstimate]: "Set estimate",
  [ActionType.setFlag]: "Flag / unflag",
  [ActionType.setVisibility]: "Set visibility",
  [ActionType.linkItem]: "Link to item",
  [ActionType.archiveItem]: "Archive / restore",
  [ActionType.addWatcher]: "Add watcher",
  [ActionType.addParticipant]: "Add participant",
  [ActionType.moveToProject]: "Move to project",
  [ActionType.createItem]: "Create item",
  [ActionType.sendWebhook]: "Send webhook",
  [ActionType.postChat]: "Post to chat",
  [ActionType.notifyUser]: "Notify user",
  [ActionType.sendEmail]: "Send email",
};

export const ACTION_TYPE_ORDER: readonly ActionTypeValue[] = [
  ActionType.setState,
  ActionType.setPriority,
  ActionType.setAssignee,
  ActionType.assignRoundRobin,
  ActionType.setTeam,
  ActionType.addLabel,
  ActionType.removeLabel,
  ActionType.setCycle,
  ActionType.setRelease,
  ActionType.setCustomField,
  ActionType.addComment,
  ActionType.setParent,
  ActionType.setType,
  ActionType.setReporter,
  ActionType.setDates,
  ActionType.setEstimate,
  ActionType.setFlag,
  ActionType.setVisibility,
  ActionType.linkItem,
  ActionType.archiveItem,
  ActionType.addWatcher,
  ActionType.addParticipant,
  ActionType.moveToProject,
  ActionType.createItem,
  ActionType.sendWebhook,
  ActionType.postChat,
  ActionType.notifyUser,
  ActionType.sendEmail,
];

/** Comment-visibility labels (add_comment action + form submit is public). */
export const COMMENT_VISIBILITY_LABELS: Record<CommentVisibilityValue, string> = {
  [CommentVisibility.public]: "Public",
  [CommentVisibility.internal]: "Internal",
};

/** Initials for avatar chips ("Hussein Jarrar" → "HJ"). */
export function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase() || "?"
  );
}

// ---------------------------------------------------------------------------
// Activity / history + related links + version control display metadata
// ---------------------------------------------------------------------------

/** Human labels for item-history change fields (`custom_field` uses the change's `name`). */
export const HISTORY_FIELD_LABELS: Record<string, string> = {
  title: "Title",
  description: "Description",
  state: "State",
  priority: "Priority",
  assignee: "Assignee",
  reporter: "Reporter",
  team: "Team",
  parent: "Parent",
  cycle: "Cycle",
  release: "Release",
  start_date: "Start date",
  target_date: "Target date",
  flagged: "Flag",
  labels: "Labels",
  links: "Dependencies",
  custom_field: "Field",
};

interface IconMeta {
  label: string;
  icon: LucideIcon;
}

export const WEBLINK_CATEGORY_META: Record<WebLinkCategoryValue, IconMeta> = {
  [WebLinkCategory.document]: { label: "Document", icon: FileText },
  [WebLinkCategory.design]: { label: "Design", icon: Palette },
  [WebLinkCategory.spec]: { label: "Spec", icon: FileCode },
  [WebLinkCategory.external]: { label: "External", icon: Link2 },
  [WebLinkCategory.other]: { label: "Other", icon: Paperclip },
};

export const WEBLINK_CATEGORY_ORDER: readonly WebLinkCategoryValue[] = [
  WebLinkCategory.document,
  WebLinkCategory.design,
  WebLinkCategory.spec,
  WebLinkCategory.external,
  WebLinkCategory.other,
];

export const VCS_REF_TYPE_META: Record<VcsRefTypeValue, IconMeta> = {
  [VcsRefType.branch]: { label: "Branch", icon: GitBranch },
  [VcsRefType.commit]: { label: "Commit", icon: GitCommitHorizontal },
  [VcsRefType.merge_request]: { label: "Merge request", icon: GitMerge },
  [VcsRefType.pull_request]: { label: "Pull request", icon: GitPullRequest },
};

/**
 * A version-control link's glyph and colour depend on its TYPE and its STATE
 * together (RADD-650): a merged pull request is not an open one with a different
 * word beside it, so it does not get the same icon. Colour carries at a glance —
 * the status chip stays for the exact term.
 *
 * Reuses the `--chart-*` state scale rather than inventing colours: `progress`
 * for work in flight (open), `done` for merged, muted for closed. Those tokens
 * already carry a validated ink tier, so the text on them clears contrast.
 */
export interface VcsRefVisual {
  icon: LucideIcon;
  label: string;
  /** Tint for the leading glyph. */
  iconClassName: string;
  /** Pill classes for the status word, when there is one. */
  pillClassName: string;
}

export function vcsRefVisual(refType: VcsRefTypeValue, status: string): VcsRefVisual {
  const base = VCS_REF_TYPE_META[refType];
  const state = status.trim().toLowerCase();
  const isRequest =
    refType === VcsRefType.pull_request || refType === VcsRefType.merge_request;

  if (isRequest && state === "merged") {
    return {
      icon: GitMerge,
      label: `${base.label} · merged`,
      iconClassName: "text-chart-done",
      pillClassName: "border-chart-done/40 bg-chart-done/12 text-chart-done-ink",
    };
  }
  if (isRequest && (state === "closed" || state === "declined")) {
    return {
      icon: GitPullRequestClosed,
      label: `${base.label} · closed`,
      iconClassName: "text-fg-faint",
      pillClassName: "border-strong bg-elevated/40 text-fg-muted",
    };
  }
  if (isRequest) {
    return {
      icon: base.icon,
      label: state ? `${base.label} · ${state}` : base.label,
      iconClassName: "text-chart-progress",
      pillClassName: "border-chart-progress/40 bg-chart-progress/12 text-chart-progress-ink",
    };
  }
  // Branches and commits have no lifecycle of their own — the glyph is the whole
  // signal, so it stays neutral rather than borrowing a state colour it does not have.
  return {
    icon: base.icon,
    label: base.label,
    iconClassName: refType === VcsRefType.commit ? "text-fg-muted" : "text-accent-text",
    pillClassName: "border-strong bg-elevated/40 text-fg-muted",
  };
}

/** CI result for a ref (spec 111): latest run, not a history. */
export const CI_STATE_META: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  success: {
    label: "Build passed",
    icon: CircleCheck,
    className: "border-chart-done/40 bg-chart-done/12 text-chart-done-ink",
  },
  failure: {
    label: "Build failed",
    icon: CircleX,
    className: "border-red-400/40 bg-red-400/12 text-red-400",
  },
  running: {
    label: "Build running",
    icon: CircleDashed,
    className: "border-chart-progress/40 bg-chart-progress/12 text-chart-progress-ink",
  },
  cancelled: {
    label: "Build cancelled",
    icon: CircleSlash,
    className: "border-strong bg-elevated/40 text-fg-muted",
  },
};

export const VCS_REF_TYPE_ORDER: readonly VcsRefTypeValue[] = [
  VcsRefType.branch,
  VcsRefType.commit,
  VcsRefType.merge_request,
  VcsRefType.pull_request,
];

export const VCS_PROVIDER_LABELS: Record<VcsProviderValue, string> = {
  [VcsProvider.manual]: "Manual",
  [VcsProvider.gitlab]: "GitLab",
  [VcsProvider.github]: "GitHub",
  [VcsProvider.forgejo]: "Forgejo",
};
