import { ItemLinkType } from "../../lib/types";
import { barRenderRightX, isBlocksViolation, type RoadmapRow } from "./roadmap-model";

/**
 * SVG overlay for the roadmap (specs 77 + 78): elbow connectors for existing
 * manual links (`blocks`/`relates`/`duplicates` — mentions are noise) whose
 * BOTH endpoints render as visible bars (filtered-out endpoints keep the red
 * "depends on" chip fallback), plus the live rubber band while a link drag is
 * in flight. `blocks` draws red — dashed AMBER when the edge is VIOLATED
 * (dependent starts on/before the blocker's end); `relates`/`duplicates` draw
 * neutral zinc. The overlay itself passes pointer events through, but each
 * elbow carries a wide invisible hit path — clicking one opens the link
 * popover (retype/remove) when the caller wires `onEdgeClick`.
 */

/** red-400 — matches the "depends on" chip the connectors replace. */
const BLOCKS_COLOR = "#f87171";
/** zinc-500 — the neutral relates/duplicates edges (spec 78). */
const NEUTRAL_COLOR = "#71717a";
/** amber-400 — a violated `blocks` ordering (spec 78). */
const VIOLATION_COLOR = "#fbbf24";
/** indigo-400 — the app's interaction accent. */
const RUBBER_COLOR = "#818cf8";
/** Horizontal lead-in/out before a connector turns. */
const STUB_PX = 8;
/** Invisible click-target width over each elbow (spec 78). */
const HIT_PATH_PX = 11;

export interface RubberBand {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** One clickable connector — everything the link popover needs. */
export interface ConnectorEdge {
  linkId: string;
  linkType: string; // link-type KEY (spec 91: types are data)
  sourceId: string;
  sourceKey: string;
  targetId: string;
  targetKey: string;
}

interface Edge extends ConnectorEdge {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
  violated: boolean;
}

/** Source right edge → target left edge, orthogonal segments only. */
function elbowPath(edge: Edge, rowHeight: number): string {
  const { sx, sy, tx, ty } = edge;
  if (tx - STUB_PX >= sx) {
    // Forward: out of the source, turn just before the target, drop in.
    if (ty === sy) return `M ${sx} ${sy} H ${tx}`;
    return `M ${sx} ${sy} H ${tx - STUB_PX} V ${ty} H ${tx}`;
  }
  // Backward: duck into the gutter between rows, run left, come back in.
  const gutterY = ty > sy ? ty - rowHeight / 2 : ty + rowHeight / 2;
  return `M ${sx} ${sy} H ${sx + STUB_PX} V ${gutterY} H ${tx - STUB_PX} V ${ty} H ${tx}`;
}

/** A row's effective window ISO — derived epics fall back to their children. */
const startIsoOf = (row: RoadmapRow) => row.item.start_date ?? row.childrenBounds?.minStart;
const targetIsoOf = (row: RoadmapRow) => row.item.target_date ?? row.childrenBounds?.maxTarget;

export function Connectors({
  rows,
  dayWidth,
  rowHeight,
  width,
  showEdges,
  rubber,
  onEdgeClick,
}: {
  /** VISIBLE rows in render order — index i sits at y = i * rowHeight. */
  rows: RoadmapRow[];
  dayWidth: number;
  rowHeight: number;
  width: number;
  showEdges: boolean;
  rubber: RubberBand | null;
  /** Present = connectors are clickable (item.update); opens the link popover. */
  onEdgeClick?: (edge: ConnectorEdge, x: number, y: number) => void;
}) {
  // One spare row of height so the rubber band isn't clipped over the open
  // drop lane below the last row.
  const height = (rows.length + 1) * rowHeight;
  const posById = new Map(rows.map((row, index) => [row.item.id, { row, index }] as const));

  const edges: Edge[] = [];
  if (showEdges) {
    for (const [, { row, index }] of posById) {
      for (const link of row.item.links?.outgoing ?? []) {
        if (link.link_type === ItemLinkType.mentions) continue; // auto-derived noise
        const target = posById.get(link.item.id);
        if (!target) continue; // endpoint filtered out — the chip covers it
        const dependentStart = startIsoOf(target.row);
        const blockerTarget = targetIsoOf(row);
        edges.push({
          linkId: link.id,
          linkType: link.link_type,
          sourceId: row.item.id,
          sourceKey: row.item.key,
          targetId: link.item.id,
          targetKey: link.item.key,
          // Off the CLAMPED right edge — min-width bars are wider than their
          // logical span, and the elbow must start at the visible edge.
          sx: barRenderRightX(row.startIndex, row.endIndex, dayWidth),
          sy: index * rowHeight + rowHeight / 2,
          tx: target.row.startIndex * dayWidth,
          ty: target.index * rowHeight + rowHeight / 2,
          violated:
            link.link_type === ItemLinkType.blocks &&
            Boolean(dependentStart && blockerTarget) &&
            isBlocksViolation(dependentStart!, blockerTarget!),
        });
      }
    }
  }

  if (edges.length === 0 && !rubber) return null;

  return (
    <svg
      width={width}
      height={height}
      className="pointer-events-none absolute top-0 z-20"
      style={{ left: 0 }}
      aria-hidden
    >
      {edges.map((edge) => {
        const color = edge.violated
          ? VIOLATION_COLOR
          : edge.linkType === ItemLinkType.blocks
            ? BLOCKS_COLOR
            : NEUTRAL_COLOR;
        const path = elbowPath(edge, rowHeight);
        return (
          <g key={edge.linkId} stroke={color} strokeOpacity={0.55}>
            <path
              d={path}
              fill="none"
              strokeWidth={1.5}
              strokeDasharray={edge.violated ? "5 4" : undefined}
            />
            <path
              d={`M ${edge.tx} ${edge.ty} l -6 -3.5 v 7 z`}
              fill={color}
              fillOpacity={0.55}
              stroke="none"
            />
            {onEdgeClick && (
              // Wide invisible hit path — the click target for the popover.
              <path
                d={path}
                fill="none"
                stroke="transparent"
                strokeWidth={HIT_PATH_PX}
                style={{ pointerEvents: "stroke", cursor: "pointer" }}
                onClick={(event) => onEdgeClick(edge, event.clientX, event.clientY)}
              >
                <title>
                  {`${edge.sourceKey} ${edge.linkType} ${edge.targetKey}${
                    edge.violated ? " — starts before its blocker ends" : ""
                  }. Click to edit.`}
                </title>
              </path>
            )}
          </g>
        );
      })}
      {rubber && (
        <g stroke={RUBBER_COLOR}>
          <line
            x1={rubber.x1}
            y1={rubber.y1}
            x2={rubber.x2}
            y2={rubber.y2}
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
          <circle cx={rubber.x2} cy={rubber.y2} r={3.5} fill={RUBBER_COLOR} stroke="none" />
        </g>
      )}
    </svg>
  );
}
