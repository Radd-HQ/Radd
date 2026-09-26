/**
 * Topology layout for nodes without stored x/y (graphs migrated by d116graphs have none; only a drag
 * persists coordinates). A layered sweep along the flow axis: each node one layer past its deepest source.
 */
import type { AutomationEdge, AutomationNode, Orientation } from "./types";

export const NODE_WIDTH = 210;
export const NODE_HEIGHT = 78;
const COLUMN_GAP = 90;
const ROW_GAP = 28;

interface Placed {
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
  orientation: Orientation = "vertical",
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

/** Every node reachable from `start` along the edges (`downstream`) or against them (`upstream`),
 * `start` included. */
export function reachable(
  edges: AutomationEdge[],
  start: Iterable<string>,
  direction: "downstream" | "upstream",
): Set<string> {
  const reached = new Set(start);
  const queue = [...reached];
  while (queue.length) {
    const id = queue.pop() as string;
    for (const edge of edges) {
      const [from, to] = direction === "downstream" ? [edge.source, edge.target] : [edge.target, edge.source];
      if (from === id && !reached.has(to)) {
        reached.add(to);
        queue.push(to);
      }
    }
  }
  return reached;
}
