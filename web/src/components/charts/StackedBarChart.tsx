import { CHART_GRID, CHART_MUTED_TEXT, niceScale, sampledIndices } from "./chart-utils";

export interface StackSegment {
  key: string;
  label: string;
  value: number;
  color: string;
}

export interface StackedBar {
  label: string;
  segments: StackSegment[];
}

interface StackedBarChartProps {
  bars: StackedBar[];
  height?: number;
  ariaLabel: string;
}

const VIEW_WIDTH = 640;
const PAD = { top: 14, right: 12, bottom: 28, left: 32 };

/**
 * Stacked vertical bars (cumulative flow) — one stack per bucket, segments in
 * StateCategory order. Hand-rolled inline SVG; the legend is rendered by the
 * caller (ChartLegend).
 */
export function StackedBarChart({ bars, height = 220, ariaLabel }: StackedBarChartProps) {
  const plotWidth = VIEW_WIDTH - PAD.left - PAD.right;
  const plotHeight = height - PAD.top - PAD.bottom;
  const totals = bars.map((bar) => bar.segments.reduce((sum, segment) => sum + segment.value, 0));
  const { max, ticks } = niceScale(Math.max(0, ...totals));
  const slot = plotWidth / Math.max(1, bars.length);
  const barWidth = Math.min(slot * 0.62, 54);
  const y = (value: number) => PAD.top + plotHeight * (1 - value / max);
  const labelEvery = new Set(sampledIndices(bars.length, 14));

  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label={ariaLabel}
      preserveAspectRatio="xMidYMid meet"
    >
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            x1={PAD.left}
            x2={VIEW_WIDTH - PAD.right}
            y1={y(tick)}
            y2={y(tick)}
            stroke={CHART_GRID}
            strokeWidth={1}
            strokeDasharray={tick === 0 ? undefined : "2 3"}
          />
          <text x={PAD.left - 6} y={y(tick) + 3} textAnchor="end" fontSize={10} fill={CHART_MUTED_TEXT}>
            {tick}
          </text>
        </g>
      ))}

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
    </svg>
  );
}
