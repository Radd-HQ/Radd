/**
 * Laying out an automation graph that carries no coordinates (spec 116).
 *
 * Every automation the d116graphs migration produced has nodes but no x/y —
 * there was no canvas when they were written. Rather than backfill positions in
 * a migration (guessing a layout for graphs nobody has opened), the canvas
 * computes one from the TOPOLOGY and only persists coordinates once someone
 * actually drags a node. So an untouched automation always opens tidy, and a
 * hand-arranged one is never re-tidied behind its owner's back.
 *
 * The layout is a layered left-to-right sweep: a node sits one column right of
 * its furthest-left source, and rows stack within a column. That reads the way
 * the graph executes, which is the point of drawing it at all.
 */
import type { AutomationEdge, AutomationNode } from "./types/automations";

export const NODE_WIDTH = 210;
export const NODE_HEIGHT = 78;
export const COLUMN_GAP = 90;
export const ROW_GAP = 28;

export interface Placed {
  node: AutomationNode;
  x: number;
  y: number;
}

/** Column index per node: 0 for a node with no sources, else max(source)+1. */
function columns(nodes: AutomationNode[], edges: AutomationEdge[]): Map<string, number> {
  const sources = new Map<string, string[]>();
  for (const edge of edges) {
    sources.set(edge.target, [...(sources.get(edge.target) ?? []), edge.source]);
  }
  const depth = new Map<string, number>();
  // Iterate to a fixed point rather than recursing: the graph is a DAG (the
  // server rejects cycles on write), but this runs on data from the wire and a
  // recursive walk would stack-overflow on a malformed one rather than settle.
  for (let pass = 0; pass < nodes.length + 1; pass++) {
    let moved = false;
    for (const node of nodes) {
      const parents = sources.get(node.id) ?? [];
      const next = parents.length
        ? Math.max(...parents.map((id) => (depth.get(id) ?? 0) + 1))
        : 0;
      if (next !== (depth.get(node.id) ?? 0)) {
        depth.set(node.id, next);
        moved = true;
      }
    }
    if (!moved) break;
  }
  for (const node of nodes) if (!depth.has(node.id)) depth.set(node.id, 0);
  return depth;
}

/**
 * Positions for every node. A node with stored x/y keeps them; the rest are
 * placed by topology, so a partly-arranged graph stays partly arranged.
 */
export function layout(
  nodes: AutomationNode[],
  edges: AutomationEdge[],
  orientation: "vertical" | "horizontal" = "vertical",
): Placed[] {
  const depth = columns(nodes, edges);
  const byColumn = new Map<number, AutomationNode[]>();
  for (const node of nodes) {
    const column = depth.get(node.id) ?? 0;
    byColumn.set(column, [...(byColumn.get(column) ?? []), node]);
  }
  const placed: Placed[] = [];
  for (const [column, columnNodes] of [...byColumn.entries()].sort((a, b) => a[0] - b[0])) {
    columnNodes.forEach((node, row) => {
      // Depth runs DOWN the page when vertical and ACROSS when horizontal;
      // siblings spread along the other axis. Stored coordinates win either way,
      // so flipping orientation never moves a node someone placed by hand.
      const alongDepth = column * (orientation === "vertical" ? NODE_HEIGHT + COLUMN_GAP : NODE_WIDTH + COLUMN_GAP);
      const alongSpread = row * (orientation === "vertical" ? NODE_WIDTH + ROW_GAP : NODE_HEIGHT + ROW_GAP);
      placed.push({
        node,
        x: node.x ?? (orientation === "vertical" ? alongSpread : alongDepth),
        y: node.y ?? (orientation === "vertical" ? alongDepth : alongSpread),
      });
    });
  }
  return placed;
}



/** A cubic bezier between two anchors — horizontal control points, so edges
 * leave and arrive flat and the eye follows the flow left to right. */
export function edgePath(
  from: { x: number; y: number },
  to: { x: number; y: number },
): string {
  const reach = Math.max(40, Math.abs(to.x - from.x) * 0.5);
  return `M ${from.x} ${from.y} C ${from.x + reach} ${from.y}, ${to.x - reach} ${to.y}, ${to.x} ${to.y}`;
}
