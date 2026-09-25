/**
 * Node SHAPES from the server (RADD-1325): the ports and outputs of a node
 * whose shape depends on its params — an AI classifier's answers, a script's
 * declared outputs, a plugin node's own rules.
 *
 * Before this the SPA computed those itself, for the node types it knew, and a
 * third-party node got its KIND's default handles — every edge wired from them
 * was refused on save. Now the editor asks `POST /automations/nodes/{type}/shape`
 * (the server's own `ports_at` / `outputs_at`) and the pure helpers
 * (`portsOfNode`, `outputsOfNode`) read the answer from this cache
 * synchronously, so none of their callers had to change shape.
 */
import { useEffect, useSyncExternalStore } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "./api";
import { apiAutomationNodeShapePath } from "./constants";
import type { AutomationCatalog, AutomationNode, OutputFieldInfo } from "./types";

export interface NodeShape {
  ports: string[];
  outputs: OutputFieldInfo[];
}

type ShapeNode = Pick<AutomationNode, "type" | "params">;

const cache = new Map<string, NodeShape>();
const listeners = new Set<() => void>();
let version = 0;

function keyOf(node: ShapeNode): string {
  return `${node.type}|${JSON.stringify(node.params ?? {})}`;
}

/** The server's answer for this node's CURRENT params, when it has arrived. */
export function cachedShape(node: ShapeNode): NodeShape | undefined {
  return cache.get(keyOf(node));
}

function isDynamic(node: ShapeNode, catalog: AutomationCatalog | undefined): boolean {
  const entry = catalog?.nodes?.find((candidate) => candidate.key === node.type);
  return Boolean(entry && (entry.dynamic_ports || entry.dynamic_outputs));
}

/** Changes whenever a shape arrives — include it in anything memoised over ports. */
export function useShapeVersion(): number {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => version,
  );
}

/** Fetch the shapes of every dynamic node in the graph. */
export function useNodeShapes(nodes: ShapeNode[], catalog: AutomationCatalog | undefined): number {
  const dynamic = nodes.filter((node) => isDynamic(node, catalog));
  const results = useQueries({
    queries: dynamic.map((node) => ({
      queryKey: ["automation-node-shape", node.type, JSON.stringify(node.params ?? {})],
      queryFn: () =>
        api.post<NodeShape>(apiAutomationNodeShapePath(node.type), { params: node.params ?? {} }),
      staleTime: Infinity,
    })),
  });
  useEffect(() => {
    let changed = false;
    results.forEach((result, index) => {
      const node = dynamic[index];
      if (!node || !result.data) return;
      const key = keyOf(node);
      if (cache.get(key) === result.data) return;
      cache.set(key, result.data);
      changed = true;
    });
    if (changed) {
      version += 1;
      for (const listener of listeners) listener();
    }
  });
  return useShapeVersion();
}
