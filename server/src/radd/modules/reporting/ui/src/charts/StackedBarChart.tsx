import type { StackedBarChartProps } from "../report-contract";
import { CHART_MUTED_TEXT, CHART_VIEW_WIDTH, ChartSvg, YGrid, niceScale, sampledIndices, useChartHeight } from "./chart-utils";

const PAD = { top: 14, right: 12, bottom: 28, left: 32 };

/** Stacked bars (cumulative flow), segments in StateCategory order; the caller renders the legend. */
export function StackedBarChart({ bars, height: requestedHeight, ariaLabel }: StackedBarChartProps) {
  const height = useChartHeight(requestedHeight, 220);
  const plotWidth = CHART_VIEW_WIDTH - PAD.left - PAD.right;
  const plotHeight = height - PAD.top - PAD.bottom;
  const totals = bars.map((bar) => bar.segments.reduce((sum, segment) => sum + segment.value, 0));
  const { max, ticks } = niceScale(Math.max(0, ...totals));
  const slot = plotWidth / Math.max(1, bars.length);
  const barWidth = Math.min(slot * 0.62, 54);
  const y = (value: number) => PAD.top + plotHeight * (1 - value / max);
  const labelEvery = new Set(sampledIndices(bars.length, 14));

  return (
    <ChartSvg height={height} ariaLabel={ariaLabel}>
      <YGrid ticks={ticks} y={y} pad={PAD} />

      {bars.map((bar, index) => {
        const slotX = PAD.left + slot * index;
        const barX = slotX + (slot - barWidth) / 2;
        let cumulative = 0;
        return (
          <g key={`${bar.label}-${index}`}>
            {bar.segments
              .filter((segment) => segment.value > 0)
              .map((segment) => {
                const top = y(cumulative + segment.value);
                const bottom = y(cumulative);
                cumulative += segment.value;
                return (
                  <rect
                    key={segment.key}
                    x={barX}
                    y={top}
                    width={barWidth}
                    height={Math.max(0, bottom - top)}
                    fill={segment.color}
                  >
                    <title>{`${bar.label} — ${segment.label}: ${segment.value}`}</title>
                  </rect>
                );
              })}
            {labelEvery.has(index) && (
              <text
                x={slotX + slot / 2}
                y={height - 9}
                textAnchor="middle"
                fontSize={10}
                fill={CHART_MUTED_TEXT}
              >
                {bar.label}
              </text>
            )}
          </g>
        );
      })}
    </ChartSvg>
  );
}
