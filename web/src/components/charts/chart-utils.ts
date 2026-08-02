/**
 * Tiny helpers shared by the hand-rolled inline-SVG charts (spec 19).
 * No chart library — just enough math for a linear y-axis and nice ticks.
 */

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

/** Shared SVG palette (dark theme): grid lines, axis text, muted text. */
export const CHART_GRID = "#3f3f46"; // zinc-700
export const CHART_AXIS_TEXT = "#a1a1aa"; // zinc-400
export const CHART_MUTED_TEXT = "#71717a"; // zinc-500

// Re-exported so the report cards keep their one-stop chart-helpers import.
export { shortDate } from "../../lib/dates";

/** Pick ~`max` roughly-even indices from `length` items (for thinning x labels). */
export function sampledIndices(length: number, max: number): number[] {
  if (length <= max) return Array.from({ length }, (_, index) => index);
  const step = (length - 1) / (max - 1);
  const result: number[] = [];
  for (let i = 0; i < max; i += 1) result.push(Math.round(i * step));
  return [...new Set(result)];
}
