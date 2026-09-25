import type { AutomationNode, OutputFieldInfo } from "./types";

export interface NodeShape { ports: string[]; outputs: OutputFieldInfo[] }
export type ShapeNode = Pick<AutomationNode, "type" | "params">;
/** Results are explicit graph inputs, never process-wide mutable state. */
export type NodeShapes = Readonly<Record<string, NodeShape>>;
export function shapeKey(node: ShapeNode): string {
  return JSON.stringify([node.type, node.params]);
}
export function shapeOf(node: ShapeNode, shapes?: NodeShapes): NodeShape | undefined {
  return shapes?.[shapeKey(node)];
}
