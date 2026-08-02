import {
  CHART_AXIS_TEXT,
  CHART_GRID,
  CHART_MUTED_TEXT,
  niceScale,
  sampledIndices,
} from "./chart-utils";

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  points: number[];
}

interface LineChartProps {
  /** One label per x position (same length as each series' points). */
  xLabels: string[];
  series: LineSeries[];
  height?: number;
  ariaLabel: string;
}

const VIEW_WIDTH = 640;
const PAD = { top: 14, right: 44, bottom: 28, left: 32 };

/**
 * Line-pair chart (burnup: scope vs completed) — hand-rolled inline SVG.
 * Series share one y-scale; x labels thin out. Legend rendered by the caller.
 */
export function LineChart({ xLabels, series, height = 220, ariaLabel }: LineChartProps) {
  const count = xLabels.length;
  const plotWidth = VIEW_WIDTH - PAD.left - PAD.right;
  const plotHeight = height - PAD.top - PAD.bottom;
  const maxValue = Math.max(0, ...series.flatMap((line) => line.points));
  const { max, ticks } = niceScale(maxValue);
  const x = (index: number) => PAD.left + (count <= 1 ? 0 : (plotWidth * index) / (count - 1));
  const y = (value: number) => PAD.top + plotHeight * (1 - value / max);
  const labelEvery = new Set(sampledIndices(count, 6));

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

      {xLabels.map((label, index) =>
        labelEvery.has(index) ? (
          <text
            key={`${label}-${index}`}
            x={x(index)}
            y={height - 9}
            textAnchor="middle"
            fontSize={10}
            fill={CHART_MUTED_TEXT}
          >
            {label}
          </text>
        ) : null,
      )}

      {series.map((line) => {
        const points = line.points.map((value, index) => `${x(index)},${y(value)}`).join(" ");
        const last = line.points[line.points.length - 1] ?? 0;
        return (
          <g key={line.key}>
            <polyline
              points={points}
              fill="none"
              stroke={line.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {count > 0 && (
              <>
                <circle cx={x(count - 1)} cy={y(last)} r={2.5} fill={line.color} />
                <text
                  x={x(count - 1) + 6}
                  y={y(last) + 3}
                  fontSize={10}
                  fill={CHART_AXIS_TEXT}
                >
                  {last}
                </text>
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}
