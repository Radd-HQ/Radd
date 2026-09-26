import { useContext, type ReactNode } from "react";
import { ChartHeightContext } from "@radd/plugin-sdk";

/** The viewBox width every chart draws in; the SVG scales to its container. */
export const CHART_VIEW_WIDTH = 640;

/** A rounded "nice" y-axis top plus its evenly-spaced tick values (incl. 0). */
export function niceScale(max: number, tickCount = 4): { max: number; ticks: number[] } {
  if (!Number.isFinite(max) || max <= 0) return { max: 1, ticks: [0, 1] };
  const rawStep = max / tickCount;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const niceStep = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
  const niceMax = Math.ceil(max / niceStep) * niceStep;
  const ticks: number[] = [];
  for (let value = 0; value <= niceMax + niceStep / 1000; value += niceStep) {
    ticks.push(Math.round(value * 1000) / 1000);
  }
  return { max: niceMax, ticks };
}

/** Theme tokens via var(): SVG fill/stroke resolve CSS variables, so charts follow light/dark. */
export const CHART_GRID = "var(--color-strong)";
export const CHART_AXIS_TEXT = "var(--color-fg-secondary)";
export const CHART_MUTED_TEXT = "var(--color-fg-muted)";

/** Pick ~`max` roughly-even indices from `length` items (for thinning x labels). */
export function sampledIndices(length: number, max: number): number[] {
  if (length <= max) return Array.from({ length }, (_, index) => index);
  const step = (length - 1) / (max - 1);
  const result: number[] = [];
  for (let i = 0; i < max; i += 1) result.push(Math.round(i * step));
  return [...new Set(result)];
}

/** The caller's height, else the dashboard widget's plot height, else `fallback`. */
export function useChartHeight(requested: number | undefined, fallback: number): number {
  const available = useContext(ChartHeightContext);
  return requested ?? available ?? fallback;
}

export function ChartSvg({ height, ariaLabel, children }: { height: number; ariaLabel: string; children: ReactNode }) {
  return (
    <svg
      viewBox={`0 0 ${CHART_VIEW_WIDTH} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label={ariaLabel}
      preserveAspectRatio="xMidYMid meet"
    >
      {children}
    </svg>
  );
}

/** Horizontal grid lines (solid at 0, dashed above) with their tick labels left of the plot. */
export function YGrid({ ticks, y, pad }: { ticks: number[]; y: (value: number) => number; pad: { left: number; right: number } }) {
  return ticks.map((tick) => (
    <g key={tick}>
      <line
        x1={pad.left}
        x2={CHART_VIEW_WIDTH - pad.right}
        y1={y(tick)}
        y2={y(tick)}
        stroke={CHART_GRID}
        strokeWidth={1}
        strokeDasharray={tick === 0 ? undefined : "2 3"}
      />
      <text x={pad.left - 6} y={y(tick) + 3} textAnchor="end" fontSize={10} fill={CHART_MUTED_TEXT}>
        {tick}
      </text>
    </g>
  ));
}
