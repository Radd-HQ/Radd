import { ListSearchInput, useListFilter } from "@radd/plugin-sdk";
import { FieldRow } from "./FieldRow";
import { MappingSection } from "./MappingSection";
import { FieldBand, type FieldBandValue, type FieldMappingEntry, type PlanProblem } from "./plan-types";

/** Below this many rows a mapping table needs no filter chrome (RADD-882). */
const FILTER_THRESHOLD = 8;

const BANDS: [FieldBandValue, string, string][] = [
  [FieldBand.in_use, "Fields with data", ""],
  [
    FieldBand.unused,
    "Unused",
    "No issue has a value — nothing to import. Expand to map one anyway.",
  ],
  [
    FieldBand.noise,
    "Not worth mapping",
    "Board ordering keys, Jira's internal blobs, and org-wide defaults.",
  ],
  [
    FieldBand.builtin,
    "Handled natively",
    "Summary, status, assignee, etc. — imported as real Radd columns.",
  ],
];

/**
 * One row per inbound Jira field, banded (spec 100).
 *
 * Only `in_use` is expanded; the rest are collapsed AND already set to ignore,
 * each carrying the reason. On a live instance that is 337 fields down to about
 * a dozen worth deciding.
 */
export function FieldsTable({
  rows,
  existingKeys,
  existingOptions = {},
  fieldLabels = {},
  nativeOptions = {},
  problems,
  highlight = "",
  onChange,
}: {
  rows: FieldMappingEntry[];
  existingKeys: string[];
  /** Current option list per field key, so a MAP row can offer to extend it. */
  existingOptions?: Record<string, string[]>;
  fieldLabels?: Record<string, string>;
  nativeOptions?: Record<string, string[]>;
  problems: PlanProblem[];
  /** A field key or Jira id a run problem pointed at — ring it and open its band. */
  highlight?: string;
  onChange: (index: number, patch: Partial<FieldMappingEntry>) => void;
}) {
  const indexById = new Map(rows.map((row, index) => [row.jira_id, index]));
  const problemFor = new Map(problems.map((p) => [p.subject, p.message]));
  const isTarget = (r: FieldMappingEntry) =>
    Boolean(highlight) && (r.target_key === highlight || r.jira_id === highlight);
  // 337 inbound fields at a live Jira: findable by name, id, or mapped key
  // (RADD-882); a filtered band holds itself open so matches can't hide.
  const search = useListFilter(rows, (r) => [r.jira_name, r.jira_id, r.target_key]);
  return (
    <div className="flex flex-col gap-3">
      {rows.length > FILTER_THRESHOLD && (
        <ListSearchInput
          value={search.filter}
          onChange={search.setFilter}
          placeholder="Filter fields by name, id, or target key…"
          total={rows.length}
          matched={search.filtered.length}
          noun="fields"
        />
      )}
      {BANDS.map(([band, title, hint]) => {
        const inBand = search.filtered.filter((r) => r.band === band);
        return (
          <MappingSection
            key={band}
            title={title}
            hint={hint}
            count={inBand.length}
            forceOpen={search.filtering}
            // A problem inside a collapsed band would be invisible while the tab
            // badge insists something is wrong.
            defaultOpen={
              band === FieldBand.in_use ||
              inBand.some((r) => problemFor.has(r.jira_id) || isTarget(r))
            }
          >
            {inBand.map((entry) => (
              <FieldRow
                key={entry.jira_id}
                entry={entry}
                index={indexById.get(entry.jira_id)!}
                existingKeys={existingKeys}
                existingOptions={existingOptions}
                fieldLabels={fieldLabels}
                nativeOptions={nativeOptions}
                problem={problemFor.get(entry.jira_id)}
                highlighted={isTarget(entry)}
                onChange={onChange}
              />
            ))}
          </MappingSection>
        );
      })}
    </div>
  );
}
