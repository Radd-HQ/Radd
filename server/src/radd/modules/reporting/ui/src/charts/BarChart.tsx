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
import type { BarChartProps } from "../report-contract";

const PAD = { top: 14, right: 12, bottom: 28, left: 32 };

/** Vertical bars (throughput, velocity), centred in even slots so two bars still read; x labels thin past 14. */
export function BarChart({ data, color, height: requestedHeight, ariaLabel }: BarChartProps) {
  const height = useChartHeight(requestedHeight, 200);
  const plotWidth = CHART_VIEW_WIDTH - PAD.left - PAD.right;
  const plotHeight = height - PAD.top - PAD.bottom;
  const { max, ticks } = niceScale(Math.max(0, ...data.map((datum) => datum.value)));
  const slot = plotWidth / Math.max(1, data.length);
  const barWidth = Math.min(slot * 0.62, 54);
  const y = (value: number) => PAD.top + plotHeight * (1 - value / max);
  const labelEvery = new Set(sampledIndices(data.length, 14));
  const showValues = data.length <= 16;

  return (
    <ChartSvg height={height} ariaLabel={ariaLabel}>
      <YGrid ticks={ticks} y={y} pad={PAD} />

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
    </ChartSvg>
  );
}
