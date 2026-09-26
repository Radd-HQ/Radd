import {
  CHART_AXIS_TEXT,
  CHART_MUTED_TEXT,
  CHART_VIEW_WIDTH,
  ChartSvg,
  YGrid,
  niceScale,
  sampledIndices,
  useChartHeight,
} from "./chart-utils";

interface LineSeries {
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

const PAD = { top: 14, right: 44, bottom: 28, left: 32 };

/** Line series on one y-scale (burnup: scope vs completed); x labels thin; the caller renders the legend. */
export function LineChart({ xLabels, series, height: requestedHeight, ariaLabel }: LineChartProps) {
  const height = useChartHeight(requestedHeight, 220);
  const count = xLabels.length;
  const plotWidth = CHART_VIEW_WIDTH - PAD.left - PAD.right;
  const plotHeight = height - PAD.top - PAD.bottom;
  const maxValue = Math.max(0, ...series.flatMap((line) => line.points));
  const { max, ticks } = niceScale(maxValue);
  const x = (index: number) => PAD.left + (count <= 1 ? 0 : (plotWidth * index) / (count - 1));
  const y = (value: number) => PAD.top + plotHeight * (1 - value / max);
  const labelEvery = new Set(sampledIndices(count, 6));

  return (
    <ChartSvg height={height} ariaLabel={ariaLabel}>
      <YGrid ticks={ticks} y={y} pad={PAD} />

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
    </ChartSvg>
  );
}
