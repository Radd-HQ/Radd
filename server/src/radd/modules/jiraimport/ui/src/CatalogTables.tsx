import { SelectField } from "@radd/plugin-sdk";
import { MAPPING_INPUT_CLASS, RowLabel } from "./MappingSection";
import {
  ComponentAction,
  VocabAction,
  type ComponentMapping,
  type LinkTypeMapping,
  type SprintMapping,
  type VersionMapping,
  type VocabActionValue,
} from "./plan-types";
import { ACTION_OPTIONS, VocabTable, type Patch } from "./VocabTable";

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
              className={`w-40 font-mono text-[12px] ${MAPPING_INPUT_CLASS}`}
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
