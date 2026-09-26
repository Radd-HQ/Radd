import type { ReactNode } from "react";
import { ListSearchInput, useListFilter } from "@radd/plugin-sdk";
import { FILTER_THRESHOLD, MappingSection, splitByUse } from "./MappingSection";
import { VocabAction, type PlanMappings, type VocabActionValue } from "./plan-types";

export const ACTION_OPTIONS: [VocabActionValue, string][] = [
  [VocabAction.create, "Create"],
  [VocabAction.map, "Map to existing"],
  [VocabAction.ignore, "Ignore"],
];

const UNUSED_HINT = "Configured in Jira but not used by this project — ignored unless you say so.";

/** Patch one row of one mapping table. */
export type Patch<K extends keyof PlanMappings> = (index: number, patch: Partial<PlanMappings[K][number]>) => void;

/** A generic used/unused pair of sections for one vocabulary. */
export function VocabTable<T extends { jira: string; count: number }>({
  rows,
  usedTitle,
  row,
}: {
  rows: T[];
  usedTitle: string;
  row: (entry: T, index: number) => ReactNode;
}) {
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
