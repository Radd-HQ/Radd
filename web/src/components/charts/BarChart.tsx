import {
  CHART_AXIS_TEXT,
  CHART_GRID,
  CHART_MUTED_TEXT,
  niceScale,
  sampledIndices,
} from "./chart-utils";

export interface BarDatum {
  label: string;
  value: number;
  /** Hover title (defaults to `label: value`). */
  title?: string;
}

interface BarChartProps {
  data: BarDatum[];
  color: string;
  height?: number;
  ariaLabel: string;
}

const VIEW_WIDTH = 640;
const PAD = { top: 14, right: 12, bottom: 28, left: 32 };

/**
 * Vertical bar chart (throughput, velocity) — hand-rolled inline SVG, no deps.
 * Bars are centered within even slots so small series (2 bars) still read well;
 * x labels thin out past ~14 bars.
 */
export function BarChart({ data, color, height = 200, ariaLabel }: BarChartProps) {
  const plotWidth = VIEW_WIDTH - PAD.left - PAD.right;
  const plotHeight = height - PAD.top - PAD.bottom;
  const { max, ticks } = niceScale(Math.max(0, ...data.map((datum) => datum.value)));
  const slot = plotWidth / Math.max(1, data.length);
  const barWidth = Math.min(slot * 0.62, 54);
  const y = (value: number) => PAD.top + plotHeight * (1 - value / max);
  const labelEvery = new Set(sampledIndices(data.length, 14));
  const showValues = data.length <= 16;

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

      {data.map((datum, index) => {
        const slotX = PAD.left + slot * index;
        const barX = slotX + (slot - barWidth) / 2;
        const barY = y(datum.value);
        const barHeight = Math.max(0, PAD.top + plotHeight - barY);
        return (
          <g key={`${datum.label}-${index}`}>
            <rect x={barX} y={barY} width={barWidth} height={barHeight} rx={2} fill={color}>
              <title>{datum.title ?? `${datum.label}: ${datum.value}`}</title>
            </rect>
            {showValues && datum.value > 0 && (
              <text
                x={slotX + slot / 2}
                y={barY - 4}
                textAnchor="middle"
                fontSize={10}
                fill={CHART_AXIS_TEXT}
              >
                {datum.value}
              </text>
            )}
            {labelEvery.has(index) && (
              <text
                x={slotX + slot / 2}
                y={height - 9}
                textAnchor="middle"
                fontSize={10}
                fill={CHART_MUTED_TEXT}
              >
                {datum.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
