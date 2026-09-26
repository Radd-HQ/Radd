import type { ChartLegendProps } from "../report-contract";

/** Swatch + label legend for the stacked-bar and line charts. */
export function ChartLegend({ entries }: ChartLegendProps) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {entries.map((entry) => (
        <li key={entry.label} className="flex items-center gap-1.5 text-[11px] text-fg-secondary">
          <span
            className="inline-block size-2.5 rounded-sm"
            style={{ backgroundColor: entry.color }}
            aria-hidden
          />
          {entry.label}
        </li>
      ))}
    </ul>
  );
}
