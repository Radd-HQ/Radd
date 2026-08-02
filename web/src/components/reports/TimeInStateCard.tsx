import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import {
  CATEGORY_CHART_COLORS,
  CATEGORY_META,
  KIND_META,
  KIND_ORDER,
} from "../../lib/meta";
import { timeInStateQuery } from "../../lib/queries";
import { ItemKind, type ItemKindValue } from "../../lib/types";
import { ReportCard } from "../charts/ReportCard";
import { Table, TBody, Td, THead, Th } from "../Table";
import { CardBody, Segmented } from "./report-state";

const KIND_FILTER = { all: "all", ...ItemKind } as const;
type KindFilterValue = (typeof KIND_FILTER)[keyof typeof KIND_FILTER];

const KIND_OPTIONS: readonly { value: KindFilterValue; label: string }[] = [
  { value: KIND_FILTER.all, label: "All" },
  ...KIND_ORDER.map((kind) => ({ value: kind, label: `${KIND_META[kind].label}s` })),
];

function formatHours(hours: number): string {
  if (hours >= 48) return `${(hours / 24).toFixed(1)} d`;
  return `${hours.toFixed(1)} h`;
}

/** Time in state: avg/median hours items spent in each category, as a table (spec 19). */
export function TimeInStateCard({
  projectId,
  initialKind,
  q,
}: {
  projectId: string;
  /** Starting kind filter (spec 75 — dashboard widgets pin it from config). */
  initialKind?: ItemKindValue;
  /** Extra SLQ ANDed into the item universe (dashboard-wide filter). */
  q?: string;
}) {
  const [kind, setKind] = useState<KindFilterValue>(initialKind ?? KIND_FILTER.all);
  const kindArg: ItemKindValue | null = kind === KIND_FILTER.all ? null : kind;
  const query = useQuery(timeInStateQuery(projectId, kindArg, q));
  const rows = query.data ?? [];

  return (
    <ReportCard
      title="Time in state"
      description="Average and median hours in each category (completed stays)"
      controls={
        <Segmented ariaLabel="Filter by kind" value={kind} options={KIND_OPTIONS} onChange={setKind} />
      }
    >
      <CardBody
        pending={query.isPending}
        error={query.isError ? errorMessage(query.error) : null}
        empty={rows.length === 0}
        emptyMessage="Not enough completed state transitions yet."
      >
        <Table>
          <THead>
            <tr>
              <Th>Category</Th>
              <Th numeric>Average</Th>
              <Th numeric>Median</Th>
              <Th numeric>Sample</Th>
            </tr>
          </THead>
          <TBody>
            {rows.map((row) => (
              <tr key={row.category}>
                <Td>
                  <span className="flex items-center gap-2 text-fg">
                    <span
                      className="size-2 rounded-full"
                      style={{ backgroundColor: CATEGORY_CHART_COLORS[row.category] }}
                      aria-hidden
                    />
                    {CATEGORY_META[row.category].label}
                  </span>
                </Td>
                <Td numeric>{formatHours(row.avg_hours)}</Td>
                <Td numeric>{formatHours(row.median_hours)}</Td>
                <Td numeric className="text-fg-muted">
                  {row.sample}
                </Td>
              </tr>
            ))}
          </TBody>
        </Table>
      </CardBody>
    </ReportCard>
  );
}
