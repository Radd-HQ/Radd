import { SelectField } from "@radd/plugin-sdk";
import { MAPPING_INPUT_CLASS, RowLabel } from "./MappingSection";
import {
  VocabAction,
  type IssueTypeMapping,
  type PriorityMapping,
  type StatusMapping,
  type VocabActionValue,
} from "./plan-types";
import type { TargetIssueType, TargetState } from "./types";
import { ACTION_OPTIONS, VocabTable, type Patch } from "./VocabTable";

/** Jira issue types → a Radd type and hierarchy level, decided per type (never guessed from the name). */
export function IssueTypesTable({
  types = [],
  rows,
  onChange,
}: {
  types?: TargetIssueType[];
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
              className={`w-44 text-[13px] ${MAPPING_INPUT_CLASS}`} /></label>
          )}
        </>
      )}
    />
  );
}

/** Jira statuses → Radd states + CATEGORY (what boards and reports read). Jira has no canceled
 * category — Rejected/Won't Do sit under `done` — so this is where that gets said. */
export function StatusesTable({
  states = [],
  rows,
  onChange,
}: {
  states?: TargetState[];
  rows: StatusMapping[];
  onChange: Patch<"statuses">;
}) {
  const categoryOf = (state: TargetState | undefined) =>
    state ? { category: state.category as StatusMapping["category"] } : {};
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
              onChange(index, { action, ...(action === VocabAction.map ? { state_name: state?.name ?? "", ...categoryOf(state) } : {}) });
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
                onChange={e => { const state = states.find(s => s.name === e.target.value); onChange(index, { state_name: e.target.value, ...categoryOf(state) }); }}>
                <option value="">Choose an existing state…</option>
                {entry.state_name && !states.some(s => s.name === entry.state_name) && <option value={entry.state_name} disabled>{entry.state_name} — not in target project</option>}
                {states.map(state => <option key={state.id} value={state.name}>{state.name} ({state.category})</option>)}
              </SelectField> : <label className="flex flex-col gap-1 text-xs text-fg-secondary">New RADD state name<input
                aria-label={`${entry.jira}: Radd state name`} value={entry.state_name}
                onChange={e => onChange(index, { state_name: e.target.value })}
                className={`w-44 text-[13px] ${MAPPING_INPUT_CLASS}`} /></label>}
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

/** Jira priorities → Radd's four, suggested from Jira's severity ORDER rather than its names. */
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
