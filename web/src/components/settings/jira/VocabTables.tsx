import type { State, IssueType } from "../../../lib/types";
import {
  ComponentAction,
  VocabAction,
  type ComponentMapping,
  type IssueTypeMapping,
  type LinkTypeMapping,
  type PlanMappings,
  type PriorityMapping,
  type SprintMapping,
  type StatusMapping,
  type VersionMapping,
  type VocabActionValue,
} from "../../../lib/types";
import { SelectField } from "../../SelectField";
import { MappingSection, RowLabel, splitByUse } from "./MappingSection";
import { useListFilter } from "../../../lib/list-filter";
import { ListSearchInput } from "../../ListSearchInput";

const ACTION_OPTIONS: [VocabActionValue, string][] = [
  [VocabAction.create, "Create"],
  [VocabAction.map, "Map to existing"],
  [VocabAction.ignore, "Ignore"],
];

const UNUSED_HINT = "Configured in Jira but not used by this project — ignored unless you say so.";

/** Below this many rows a vocabulary table needs no filter chrome (RADD-882). */
const FILTER_THRESHOLD = 8;

/** A generic used/unused pair of sections for one vocabulary. */
function VocabTable<T extends { jira: string; count: number }>({
  rows,
  usedTitle,
  row,
}: {
  rows: T[];
  usedTitle: string;
  row: (entry: T, index: number) => React.ReactNode;
}) {
  // 83 statuses / 59 types at a live Jira (RADD-882): filter by the Jira value;
  // the unused fold holds itself open while filtering so matches can't hide.
  const search = useListFilter(rows, (entry) => [entry.jira]);
  const [used, unused] = splitByUse(search.filtered);
  const indexes = new Map(rows.map((entry, index) => [entry.jira, index]));
  return (
    <div className="flex flex-col gap-3">
      {rows.length > FILTER_THRESHOLD && (
        <ListSearchInput
          value={search.filter}
          onChange={search.setFilter}
          placeholder="Filter by Jira value…"
          total={rows.length}
          matched={search.filtered.length}
          noun="values"
        />
      )}
      <MappingSection title={usedTitle} count={used.length} defaultOpen forceOpen={search.filtering}>
        {used.map((entry) => (
          <div key={entry.jira} className="flex flex-wrap items-center gap-2 px-3 py-2">
            {row(entry, indexes.get(entry.jira)!)}
          </div>
        ))}
      </MappingSection>
      <MappingSection
        title="Not used by this project"
        hint={UNUSED_HINT}
        count={unused.length}
        forceOpen={search.filtering}
      >
        {unused.map((entry) => (
          <div key={entry.jira} className="flex flex-wrap items-center gap-2 px-3 py-2">
            {row(entry, indexes.get(entry.jira)!)}
          </div>
        ))}
      </MappingSection>
    </div>
  );
}

type Patch<K extends keyof PlanMappings> = (index: number, patch: Partial<PlanMappings[K][number]>) => void;

/**
 * Jira issue types → Radd's two orthogonal axes.
 *
 * Spec 90 collapsed this to `"epic" in name` / `"sub" in name`, so "Initiative",
 * "Milestone" and every renamed or translated type silently became a plain issue
 * with no way to correct it.
 */
export function IssueTypesTable({
  types = [],
  rows,
  onChange,
}: {
  types?: IssueType[];
  rows: IssueTypeMapping[];
  onChange: Patch<"issue_types">;
}) {
  return (
    <VocabTable
      rows={rows}
      usedTitle="Issue types in use"
      row={(entry, index) => (
        <>
          <RowLabel value={entry.jira} count={entry.count} />
          <SelectField
            label="Hierarchy level"
            ariaLabel={`${entry.jira}: hierarchy level`}
            className="w-32"
            value={entry.kind}
            onChange={(e) => onChange(index, { kind: e.target.value as IssueTypeMapping["kind"] })}
          >
            <option value="epic">Epic</option>
            <option value="issue">Issue</option>
            <option value="subtask">Subtask</option>
          </SelectField>
          <SelectField
            label="Action"
            ariaLabel={`${entry.jira}: what to do`}
            className="w-36"
            value={entry.action}
            onChange={(e) => onChange(index, { action: e.target.value as VocabActionValue })}
          >
            {ACTION_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label} type
              </option>
            ))}
          </SelectField>
          {entry.action !== VocabAction.ignore && (
            entry.action === VocabAction.map ? <SelectField label="Existing RADD type" value={entry.type_name}
              onChange={e => onChange(index, { type_name: e.target.value })}>
              <option value="">Choose an existing type…</option>
              {entry.type_name && !types.some(t => t.name === entry.type_name) && <option value={entry.type_name} disabled>{entry.type_name} — not in target project</option>}
              {types.map(type => <option key={type.id} value={type.name}>{type.name}</option>)}
            </SelectField> : <label className="flex flex-col gap-1 text-xs text-fg-secondary">New RADD type name<input
              aria-label={`${entry.jira}: Radd type name`} value={entry.type_name}
              onChange={e => onChange(index, { type_name: e.target.value })}
              className="h-8 w-44 rounded-md border border-strong bg-surface px-2.5 text-heading" /></label>
          )}
        </>
      )}
    />
  );
}

/**
 * Jira statuses → Radd states + CATEGORY.
 *
 * The category is what analytics, boards and rollover read. Jira has no
 * "cancelled" category — it files Rejected / Won't Do under `done` — so this is
 * where you say that "Rejeté" actually means canceled. Spec 90 tested the
 * literal English words and got everything else wrong.
 */
export function StatusesTable({
  states = [],
  rows,
  onChange,
}: {
  states?: State[];
  rows: StatusMapping[];
  onChange: Patch<"statuses">;
}) {
  return (
    <VocabTable
      rows={rows}
      usedTitle="Statuses in use"
      row={(entry, index) => (
        <>
          <RowLabel value={entry.jira} count={entry.count} />
          <SelectField
            label="Action"
            ariaLabel={`${entry.jira}: what to do`}
            className="w-36"
            value={entry.action}
            onChange={(e) => {
              const action = e.target.value as VocabActionValue;
              const state = states.find(s => s.name === entry.state_name);
              onChange(index, { action, ...(action === VocabAction.map ? { state_name: state?.name ?? "", ...(state ? { category: state.category } : {}) } : {}) });
            }}
          >
            {ACTION_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label} state
              </option>
            ))}
          </SelectField>
          {entry.action !== VocabAction.ignore && (
            <>
              {entry.action === VocabAction.map ? <SelectField label="Existing RADD state" value={entry.state_name}
                onChange={e => { const state = states.find(s => s.name === e.target.value); onChange(index, { state_name: e.target.value, ...(state ? { category: state.category } : {}) }); }}>
                <option value="">Choose an existing state…</option>
                {entry.state_name && !states.some(s => s.name === entry.state_name) && <option value={entry.state_name} disabled>{entry.state_name} — not in target project</option>}
                {states.map(state => <option key={state.id} value={state.name}>{state.name} ({state.category})</option>)}
              </SelectField> : <label className="flex flex-col gap-1 text-xs text-fg-secondary">New RADD state name<input
                aria-label={`${entry.jira}: Radd state name`} value={entry.state_name}
                onChange={e => onChange(index, { state_name: e.target.value })}
                className="h-8 w-44 rounded-md border border-strong bg-surface px-2.5 text-heading" /></label>}
              <SelectField
                label="Reporting category"
                hint={entry.action === VocabAction.map ? "Uses the existing state’s category." : "Controls boards, reports and completed-work handling."}
                disabled={entry.action === VocabAction.map}
                ariaLabel={`${entry.jira}: state category`}
                className="w-36"
                value={entry.category}
                onChange={(e) =>
                  onChange(index, { category: e.target.value as StatusMapping["category"] })
                }
              >
                <option value="triage">Triage</option>
                <option value="backlog">Backlog</option>
                <option value="todo">To do</option>
                <option value="in_progress">In progress</option>
                <option value="done">Done</option>
                <option value="canceled">Canceled</option>
              </SelectField>
            </>
          )}
        </>
      )}
    />
  );
}

/**
 * Jira priorities → Radd's four.
 *
 * Suggested from Jira's own severity ORDER rather than a name table, so P1/P2/P3
 * and Urgent/Normal both land correctly — spec 90 sent anything unrecognised to
 * `normal` with no way to fix it.
 */
export function PrioritiesTable({
  rows,
  onChange,
}: {
  rows: PriorityMapping[];
  onChange: Patch<"priorities">;
}) {
  return (
    <VocabTable
      rows={rows}
      usedTitle="Priorities in use"
      row={(entry, index) => (
        <>
          <RowLabel value={entry.jira} count={entry.count} />
          <SelectField
            label=""
            ariaLabel={`${entry.jira}: Radd priority`}
            className="w-36"
            value={entry.priority}
            onChange={(e) =>
              onChange(index, { priority: e.target.value as PriorityMapping["priority"] })
            }
          >
            <option value="blocker">Blocker</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </SelectField>
        </>
      )}
    />
  );
}

/** Jira link types → Radd link types, which spec 91 made definable. */
export function LinkTypesTable({
  rows,
  onChange,
}: {
  rows: LinkTypeMapping[];
  onChange: Patch<"link_types">;
}) {
  return (
    <VocabTable
      rows={rows}
      usedTitle="Link types in use"
      row={(entry, index) => (
        <>
          <RowLabel
            value={entry.jira}
            count={entry.count}
            detail={entry.outward_name ? `“${entry.outward_name}”` : undefined}
          />
          <SelectField
            label="Action"
            ariaLabel={`${entry.jira}: what to do`}
            className="w-36"
            value={entry.action}
            onChange={(e) => onChange(index, { action: e.target.value as VocabActionValue })}
          >
            {ACTION_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </SelectField>
          {entry.action !== VocabAction.ignore && (
            <input
              aria-label={`${entry.jira}: Radd link-type key`}
              value={entry.key}
              onChange={(e) => onChange(index, { key: e.target.value.toLowerCase() })}
              className="h-8 w-40 rounded-md border border-strong bg-surface px-2.5 font-mono text-[12px] text-heading outline-none focus-visible:outline-2 focus-visible:outline-focus"
            />
          )}
        </>
      )}
    />
  );
}

/** Jira sprints → Radd cycles, keeping dates so a closed sprint imports completed. */
export function SprintsTable({
  rows,
  onChange,
}: {
  rows: SprintMapping[];
  onChange: Patch<"sprints">;
}) {
  return (
    <VocabTable
      rows={rows}
      usedTitle="Sprints"
      row={(entry, index) => (
        <>
          <RowLabel
            value={entry.jira}
            count={entry.count}
            detail={[entry.state, entry.start_date, entry.end_date].filter(Boolean).join(" · ")}
          />
          <SelectField
            label="Action"
            ariaLabel={`${entry.jira}: what to do`}
            className="w-36"
            value={entry.action}
            onChange={(e) => onChange(index, { action: e.target.value as VocabActionValue })}
          >
            <option value={VocabAction.create}>Create cycle</option>
            <option value={VocabAction.ignore}>Ignore</option>
          </SelectField>
        </>
      )}
    />
  );
}

/** Jira fix versions → Radd releases. Not imported at all before spec 100. */
export function VersionsTable({
  rows,
  onChange,
}: {
  rows: VersionMapping[];
  onChange: Patch<"versions">;
}) {
  return (
    <VocabTable
      rows={rows}
      usedTitle="Fix versions"
      row={(entry, index) => (
        <>
          <RowLabel value={entry.jira} count={entry.count} />
          <SelectField
            label="Action"
            ariaLabel={`${entry.jira}: what to do`}
            className="w-40"
            value={entry.action}
            onChange={(e) => onChange(index, { action: e.target.value as VocabActionValue })}
          >
            <option value={VocabAction.create}>Create release</option>
            <option value={VocabAction.ignore}>Ignore</option>
          </SelectField>
        </>
      )}
    />
  );
}

/** Jira components — Radd has no equivalent, so this is a real decision. */
export function ComponentsTable({
  rows,
  onChange,
}: {
  rows: ComponentMapping[];
  onChange: Patch<"components">;
}) {
  return (
    <VocabTable
      rows={rows}
      usedTitle="Components"
      row={(entry, index) => (
        <>
          <RowLabel value={entry.jira} count={entry.count} />
          <SelectField
            label="Action"
            ariaLabel={`${entry.jira}: what to do`}
            className="w-40"
            value={entry.action}
            onChange={(e) =>
              onChange(index, { action: e.target.value as ComponentMapping["action"] })
            }
          >
            <option value={ComponentAction.label}>Add as a label</option>
            <option value={ComponentAction.ignore}>Ignore</option>
          </SelectField>
        </>
      )}
    />
  );
}
