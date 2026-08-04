import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Slot, SlotId } from "@radd/plugin-sdk";
import { ChevronDown, ChevronRight, SlidersHorizontal } from "lucide-react";
import { SidePanelCollapse } from "../SidePanel";
import {
  useAllowedTransitions,
  useItemWritability,
  usePointsEnabled,
} from "../../lib/hooks";
import { PRIORITY_META, PRIORITY_ORDER } from "../../lib/meta";
import {
  effectiveScreenQuery,
  issueTypesQuery,
  itemSlaQuery,
  teamsQuery,
  usersQuery,
} from "../../lib/queries";
import { ValueChip } from "./ValueChip";

/** Chip hex per state category / priority (the OtherTracker colored-letter chips). */
const CATEGORY_CHIP: Record<string, string> = {
  triage: "#f59e0b",
  backlog: "#71717a",
  todo: "#3b82f6",
  in_progress: "#eab308",
  done: "#22c55e",
  canceled: "#52525b",
};
const PRIORITY_CHIP: Record<string, string> = {
  blocker: "#ef4444",
  high: "#f97316",
  normal: "#64748b",
  low: "#3f3f46",
};

/** A rail row: a value chip + its picker, side by side (State/Type/Priority). */
function ChipSelect({ chip, children }: { chip: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-end gap-2">
      <span className="mb-1.5">{chip}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
import {
  ScreenPlacement,
  type CustomFieldValue,
  type CustomFields,
  type EffectiveFieldRow,
  type FieldDef,
  type Item,
  type ItemUpdate,
  type PriorityValue,
  type Project,
  type State,
} from "../../lib/types";
import { SelectField } from "../SelectField";
import { PersonName } from "../PersonName";
import { CustomFieldControl } from "./CustomFieldsForm";
import { LabelsEditor } from "./LabelsEditor";
import { CyclePicker, DateField, ReleasePicker } from "./PlanningFields";
import { SlaTimerChip } from "./SlaChips";
import { TimeTrackingPanel } from "./TimeTrackingPanel";

interface IssuePropertiesProps {
  project: Project;
  item: Item;
  patch: (patch: ItemUpdate) => void;
  states: State[] | undefined;
  fields: FieldDef[];
  customFields: CustomFields;
  fieldErrors: Record<string, string>;
  onCustomFieldChange: (key: string, value: CustomFieldValue) => void;
  timeloggingEnabled: boolean;
}

// Builtin fields a screen can arrange, in their fallback order (mirrors the backend
// DEFAULT_BUILTIN_ORDER) — used until the effective-screen query resolves.
const SCREEN_BUILTIN_ORDER = [
  "assignee",
  "reporter",
  "team",
  "cycle",
  "release",
  "start_date",
  "target_date",
  "labels",
  "sla",
  "time_tracking",
  "points",
] as const;

/** The default layout (builtins primary — points secondary, spec 70 — custom fields
 * secondary) shown for the brief window before `GET /screens/effective` resolves. */
function clientDefaultScreen(fields: FieldDef[]): EffectiveFieldRow[] {
  return [
    ...SCREEN_BUILTIN_ORDER.map((field) => ({
      field,
      placement: field === "points" ? ScreenPlacement.secondary : ScreenPlacement.primary,
      custom: false,
    })),
    ...fields.map((f) => ({ field: `cf:${f.key}`, placement: ScreenPlacement.secondary, custom: true })),
  ];
}

/**
 * Right-rail "properties" panel for the item detail view (issue-view redesign).
 * All the metadata — status, people, planning, labels, custom fields, time
 * tracking — is grouped out of the reading column so the summary, description,
 * and comments stay front-and-centre. On the full page it renders as a compact
 * 288px rail (fields stacked); inside the narrow side panel it spans full width
 * and its own container query relaxes the compact selects into two columns.
 * Secondary fields and time tracking collapse by default in BOTH surfaces —
 * first-glance info stays above the fold, the rest is one click away.
 */
export function IssueProperties({
  project,
  item,
  patch,
  states,
  fields,
  customFields,
  fieldErrors,
  onCustomFieldChange,
  timeloggingEnabled,
}: IssuePropertiesProps) {
  // Writability (spec 92): item.update + per-field grants resolved server-side. Every editor below
  // DISABLES up front (dimmed, with a reason) when the user can't write it — never edit-then-error.
  const writ = useItemWritability(project);
  // Transition guards (spec 61): disallowed target states gray out with a
  // tooltip listing the failing checks. Off mode = everything allowed.
  const transitions = useAllowedTransitions(item.id);
  // Story points (spec 70): the rail's Points field only exists where the
  // project opted in — a non-opted-in project shows zero points UI.
  const pointsEnabled = usePointsEnabled(project.id);
  // The item's issue-type + project resolve the field layout (spec 53 screens).
  const screen = useQuery(effectiveScreenQuery(project.id, item.type?.id ?? null));
  const layout = screen.data?.fields ?? clientDefaultScreen(fields);
  const fieldByKey = new Map(fields.map((f) => [f.key, f] as const));

  const renderField = (row: EffectiveFieldRow): FieldNode | null => {
    switch (row.field) {
      case "assignee":
        return { node: <AssigneePicker item={item} onPatch={patch} />, selfPadded: false };
      case "reporter":
        return { node: <ReporterPicker item={item} onPatch={patch} />, selfPadded: false };
      case "team":
        return {
          node: <TeamPicker item={item} onPatch={patch} />,
          selfPadded: false,
        };
      case "cycle":
        return {
          node: <CyclePicker item={item} onPatch={patch} />,
          selfPadded: false,
        };
      case "release":
        return {
          node: <ReleasePicker projectId={project.id} item={item} onPatch={patch} />,
          selfPadded: false,
        };
      case "start_date":
        return {
          node: (
            <DateField
              label="Start date"
              value={item.start_date ?? null}
              onChange={(value) => patch({ start_date: value })}
            />
          ),
          selfPadded: false,
        };
      case "target_date":
        return {
          node: (
            <DateField
              label="Target date"
              value={item.target_date ?? null}
              onChange={(value) => patch({ target_date: value })}
            />
          ),
          selfPadded: false,
        };
      case "labels":
        return {
          node: <LabelsEditor value={item.labels} onChange={(labels) => patch({ labels })} />,
          selfPadded: false,
        };
      case "points":
        return pointsEnabled
          ? { node: <PointsField item={item} onPatch={patch} />, selfPadded: false }
          : null;
      case "sla":
        // Self-renders (with padding) or returns null when no policy applies.
        return { node: <SlaPanel itemId={item.id} />, selfPadded: true };
      case "time_tracking":
        return timeloggingEnabled
          ? {
              node: <TimeTrackingSection project={project} itemId={item.id} />,
              selfPadded: true,
            }
          : null;
      default: {
        if (!row.custom) return null;
        const key = row.field.slice(3); // strip the "cf:" prefix
        const def = fieldByKey.get(key);
        if (!def) return null; // field not readable / not in this project's scope
        return {
          node: (
            <CustomFieldControl
              field={def}
              value={customFields[key] ?? null}
              error={fieldErrors[key]}
              onChange={(value) => onCustomFieldChange(key, value)}
            />
          ),
          selfPadded: false,
        };
      }
    }
  };

  // A custom field with a validation error must never be hidden/collapsed away.
  const placementOf = (row: EffectiveFieldRow): string =>
    row.custom && fieldErrors[row.field.slice(3)] ? ScreenPlacement.primary : row.placement;

  // Per-row lock: `sla`/`time_tracking` self-render read-only surfaces (never gated); every other
  // row (the builtin names — `points` is the `estimate_points` rule field since RADD-834 — plus
  // `cf:<key>` custom fields) resolves through the per-field grant signal.
  const lockFor = (fieldRow: string): { locked: boolean; reason: string } => {
    if (fieldRow === "sla" || fieldRow === "time_tracking") return { locked: false, reason: "" };
    const name =
      fieldRow === "points"
        ? "estimate_points"
        : fieldRow.startsWith("cf:")
          ? fieldRow.slice(3)
          : fieldRow;
    return { locked: !writ.fieldWritable(name), reason: writ.reasonFor(name) };
  };

  const primary = layout.filter((row) => placementOf(row) === ScreenPlacement.primary);
  const secondary = layout.filter((row) => placementOf(row) === ScreenPlacement.secondary);

  return (
    <div className="@container flex flex-col divide-y divide-subtle rounded-xl border border-subtle bg-surface shadow-lift">
      {/* The card's own heading (the rail is frameless — no banner above the
          cards); the collapse toggle for the whole rail rides here. */}
      <div className="flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <SlidersHorizontal size={12} aria-hidden />
        Fields
        <SidePanelCollapse className="ml-auto" />
      </div>
      {/* Core identity — always shown, always first. */}
      <div className="flex flex-col gap-3 p-4">
        <ChipSelect
          chip={
            <ValueChip
              label={item.state.name}
              color={CATEGORY_CHIP[item.state.category] ?? "#71717a"}
            />
          }
        >
          <SelectField
            label="State"
            value={item.state.id}
            disabled={!writ.fieldWritable("state")}
            title={writ.fieldWritable("state") ? undefined : writ.reasonFor("state")}
            onChange={(event) => patch({ state_id: event.target.value })}
          >
            {[...(states ?? [])]
              .sort((a, b) => a.position - b.position)
              .map((state) => {
                const blocked = !transitions.isAllowed(state.id);
                return (
                  <option
                    key={state.id}
                    value={state.id}
                    disabled={blocked}
                    title={blocked ? transitions.failuresFor(state.id).join("; ") : undefined}
                  >
                    {state.name}
                    {blocked ? " (blocked)" : ""}
                  </option>
                );
              })}
          </SelectField>
        </ChipSelect>

        <TypePicker
          projectId={project.id}
          item={item}
          onPatch={patch}
          locked={!writ.canEdit}
          reason={writ.reasonFor("type")}
        />

        <ChipSelect
          chip={
            <ValueChip
              label={PRIORITY_META[item.priority].label}
              color={PRIORITY_CHIP[item.priority] ?? "#64748b"}
            />
          }
        >
          <SelectField
            label="Priority"
            value={item.priority}
            disabled={!writ.fieldWritable("priority")}
            title={writ.fieldWritable("priority") ? undefined : writ.reasonFor("priority")}
            onChange={(event) => patch({ priority: event.target.value as PriorityValue })}
          >
            {PRIORITY_ORDER.map((value) => (
              <option key={value} value={value}>
                {PRIORITY_META[value].label}
              </option>
            ))}
          </SelectField>
        </ChipSelect>
      </div>

      {/* Plugin-contributed issue-rail sections (spec 94): federated remotes register here. The
          mailintake external-requester chip, participants, CSAT and approvals cards all arrive
          through this slot from their own remotes — the host imports none of them. */}
      <Slot id={SlotId.issuePanelSection} item={item} project={project} />

      {primary.map((row) => {
        const lock = lockFor(row.field);
        return (
          <FieldSlot key={row.field} render={renderField(row)} locked={lock.locked} reason={lock.reason} />
        );
      })}

      {secondary.length > 0 && (
        <MoreFields count={secondary.length}>
          {secondary.map((row) => {
            const lock = lockFor(row.field);
            return (
              <FieldSlot key={row.field} render={renderField(row)} locked={lock.locked} reason={lock.reason} />
            );
          })}
        </MoreFields>
      )}

      {/* Plugin-contributed sections BELOW the fields (spec 94): a plugin adds its own section under
          the Fields area by registering an `issue.rail.bottom` slot. */}
      <Slot id={SlotId.issueRailBottom} item={item} project={project} />
    </div>
  );
}

interface FieldNode {
  node: ReactNode;
  selfPadded: boolean;
}

/** Wraps a rail field in consistent padding, unless the field brings its own. When `locked`, a
 *  `<fieldset disabled>` makes every control inside inert natively, dims it (readable), and carries
 *  the reason as a hover title — the edit can't fire, so there's nothing to error on save. */
function FieldSlot({
  render,
  locked,
  reason,
}: {
  render: FieldNode | null;
  locked: boolean;
  reason: string;
}) {
  if (!render) return null;
  if (render.selfPadded) return <>{render.node}</>;
  return (
    <fieldset
      disabled={locked}
      title={locked ? reason : undefined}
      className="min-w-0 px-4 py-3 disabled:opacity-70"
    >
      {render.node}
    </fieldset>
  );
}

/** The collapsible "secondary" fields group — collapsed by default everywhere. */
function MoreFields({ count, children }: { count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex items-center gap-1.5 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-fg-muted hover:text-fg cursor-pointer focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
      >
        <Chevron size={13} aria-hidden />
        More fields
        <span className="ml-1 rounded bg-elevated px-1.5 text-[11px] text-fg-secondary">{count}</span>
      </button>
      {open && (
        <div className="flex flex-col divide-y divide-subtle border-t border-subtle/60">
          {children}
        </div>
      )}
    </div>
  );
}

function RailHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-fg-muted">{children}</h3>
  );
}

/**
 * The rail's time-tracking widget: collapsed it shows the peek-style summary
 * (progress bar + estimate/entry line); expanded it is the full panel with the
 * estimate editor, log-work form, and the worklog list. Collapsed by default
 * on BOTH the full page and the peek — totals are the first-glance info, the
 * history is one click away.
 */
function TimeTrackingSection({ project, itemId }: { project: Project; itemId: string }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div className="p-4">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="mb-3 flex w-full items-center gap-1.5 text-left text-xs font-semibold uppercase tracking-wide text-fg-muted hover:text-fg cursor-pointer focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
      >
        <Chevron size={13} aria-hidden />
        Time tracking
      </button>
      <TimeTrackingPanel project={project} itemId={itemId} compact={!open} />
    </div>
  );
}

interface PickerProps {
  item: Item;
  onPatch: (patch: ItemUpdate) => void;
}

/** Issue-type picker (spec 51) — the classification chip + a dropdown. */
function TypePicker({
  projectId,
  item,
  onPatch,
  locked,
  reason,
}: PickerProps & { projectId: string; locked: boolean; reason: string }) {
  const types = useQuery(issueTypesQuery(projectId));
  return (
    <div className="flex items-end gap-2">
      {item.type && (
        <span className="mb-1.5">
          <ValueChip label={item.type.name} color={item.type.color} icon={item.type.icon} />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <SelectField
          label="Type"
          value={item.type?.id ?? ""}
          disabled={locked}
          title={locked ? reason : undefined}
          onChange={(event) => onPatch({ type_id: event.target.value || null })}
        >
          <option value="">None</option>
          {(types.data ?? []).map((issueType) => (
            <option key={issueType.id} value={issueType.id}>
              {issueType.name}
            </option>
          ))}
        </SelectField>
      </div>
    </div>
  );
}

/**
 * Story-points input (spec 70): 0–999, one decimal; committed on blur/Enter so
 * typing doesn't spam PATCHes. Empty clears (explicit null). Only mounted when
 * the project has points enabled.
 */
function PointsField({ item, onPatch }: PickerProps) {
  const current = item.estimate_points != null ? String(item.estimate_points) : "";
  const [draft, setDraft] = useState(current);
  useEffect(() => setDraft(current), [current]);

  const commit = () => {
    if (draft === current) return;
    if (draft.trim() === "") {
      onPatch({ estimate_points: null });
      return;
    }
    const parsed = Number(draft);
    if (Number.isFinite(parsed) && parsed >= 0 && parsed <= 999) {
      onPatch({ estimate_points: parsed });
    } else {
      setDraft(current); // out of bounds / garbage — snap back
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="points-field" className="text-xs font-medium text-fg-secondary">
        Points
      </label>
      <input
        id="points-field"
        type="number"
        inputMode="decimal"
        min={0}
        max={999}
        step={0.5}
        placeholder="—"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        className="h-8 w-full rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
    </div>
  );
}

/** Assignee picker (`GET /users`) — spec-02 field. */
function AssigneePicker({ item, onPatch }: PickerProps) {
  const users = useQuery(usersQuery);
  return (
    <SelectField
      label="Assignee"
      value={item.assignee?.id ?? ""}
      onChange={(event) => onPatch({ assignee_id: event.target.value || null })}
    >
      <option value="">Unassigned</option>
      {(users.data ?? [])
        .filter((user) => user.active)
        .map((user) => (
          <option key={user.id} value={user.id}>
            <PersonName user={user} />
          </option>
        ))}
    </SelectField>
  );
}

/** Reporter/requester picker (spec 30) — who raised the issue; defaults to creator. */
function ReporterPicker({ item, onPatch }: PickerProps) {
  const users = useQuery(usersQuery);
  return (
    <SelectField
      label="Reporter"
      value={item.reporter?.id ?? ""}
      onChange={(event) => onPatch({ reporter_id: event.target.value || null })}
    >
      <option value="">Unknown</option>
      {(users.data ?? [])
        .filter((user) => user.active)
        .map((user) => (
          <option key={user.id} value={user.id}>
            <PersonName user={user} />
          </option>
        ))}
    </SelectField>
  );
}

/**
 * SLA timers (spec 30): rendered only when a policy applies to the item — the
 * item's MATCHED policy since spec 63 (at most one entry). Live server
 * compute; refreshed every minute + on realtime item pushes.
 */
function SlaPanel({ itemId }: { itemId: string }) {
  const { data } = useQuery(itemSlaQuery(itemId));
  if (!data || data.entries.length === 0) return null;
  return (
    <div className="p-4">
      <RailHeading>SLA</RailHeading>
      <div className="flex flex-col gap-2">
        {data.entries.map((entry) => (
          <div key={entry.policy_id}>
            <p className="mb-1 text-[11px] text-fg-muted">{entry.policy_name}</p>
            <ul className="flex flex-col gap-1">
              {entry.timers.map((timer) => (
                <li key={timer.kind} className="flex items-center gap-2 text-xs">
                  <span className="capitalize text-fg-secondary">{timer.kind}</span>
                  <SlaTimerChip timer={timer} className="ml-auto" />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Team picker (`GET /teams`) — spec-02 field. */
function TeamPicker({ item, onPatch }: PickerProps) {
  const teams = useQuery(teamsQuery());
  return (
    <SelectField
      label="Team"
      value={item.team?.id ?? ""}
      onChange={(event) => onPatch({ team_id: event.target.value || null })}
      hint={(teams.data ?? []).length === 0 ? "No teams yet" : undefined}
    >
      <option value="">None</option>
      {(teams.data ?? []).map((team) => (
        <option key={team.id} value={team.id}>
          {team.name}
        </option>
      ))}
    </SelectField>
  );
}
