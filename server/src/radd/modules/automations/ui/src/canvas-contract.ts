import type { AutomationNode, AutomationEdge, AutomationCatalog, Orientation, RuleTestResult } from "./types";
import type { NodeShapes } from "./shape-contract";
export const GRAPH_CANVAS_SLOT = "automation.graph.canvas";

export interface GraphCanvasProps {
  /** Explicit shapes from an editor; omitted previews resolve their own shapes. */
  shapes?: NodeShapes;
  nodes: AutomationNode[];
  edges: AutomationEdge[];
  onNodesChange?: (nodes: AutomationNode[]) => void;
  onConnect?: (edge: AutomationEdge) => void;
  onSelect?: (nodeId: string | null) => void;
  /** Nodes removed by React Flow's own delete key. Separate from
   * `onNodesChange` because a removal is not a move: it must also drop the
   * edges that touched the node, which only the graph owner can do. */
  onNodesDelete?: (nodeIds: string[]) => void;
  /** Edges removed by the delete key. */
  onEdgesDelete?: (edges: AutomationEdge[]) => void;
  /** Which way the graph flows. Ports, layout and edge curves all follow it. */
  orientation?: Orientation;
  /** Right-click on empty canvas — the Nuke-style add menu hangs off this. */
  onCanvasContextMenu?: (at: { x: number; y: number }) => void;
  /** Only for the arity badge; optional so a preview renders before the catalog resolves. */
  catalog?: AutomationCatalog;
  /** The last dry run, so each node can say what reached it and each port what
   * left. Null clears the annotations. */
  run?: RuleTestResult | null;
  /** No editing affordances (the version preview). */
  readOnly?: boolean;
  /** Per VALIDATE trigger id (RADD-1329): can anything it reaches refuse a
   * submission ("blocks": a Block submission node) or does it only advise. */
  validationChips?: Readonly<Record<string, "blocks" | "advises">>;
}
