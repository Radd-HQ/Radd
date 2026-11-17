import type { ChartLegendProps } from "../report-contract";

/** Swatch + label legend for the stacked-bar and line charts. An entry that
 *  carries `onToggle` is a button: pressed = its series is drawn (RADD-1557). */
export function ChartLegend({ entries }: ChartLegendProps) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {entries.map((entry) => {
        const swatch = (
          <span
            className="inline-block size-2.5 rounded-sm"
            style={{ backgroundColor: entry.color, opacity: entry.hidden ? 0.35 : 1 }}
            aria-hidden
          />
        );
        return (
          <li key={entry.label} className="flex items-center text-meta text-fg-secondary">
            {entry.onToggle ? (
              <button
                type="button"
                aria-pressed={!entry.hidden}
                onClick={entry.onToggle}
                title={entry.hidden ? `Show ${entry.label}` : `Hide ${entry.label}`}
                data-legend-toggle={entry.label}
                className={`flex items-center gap-1.5 rounded px-1 py-0.5 outline-focus hover:bg-elevated focus-visible:outline-2 cursor-pointer ${
                  entry.hidden ? "text-fg-muted line-through" : ""
                }`}
              >
                {swatch}
                {entry.label}
              </button>
            ) : (
              <span className="flex items-center gap-1.5">
                {swatch}
                {entry.label}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
