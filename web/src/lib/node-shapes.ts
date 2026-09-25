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
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "./api";
import { apiAutomationNodeShapePath } from "./constants";
import type { AutomationCatalog, AutomationNode, OutputFieldInfo } from "./types";

export interface NodeShape {
  ports: string[];
  outputs: OutputFieldInfo[];
}

type ShapeNode = Pick<AutomationNode, "type" | "params"> & { id?: string };

const cache = new Map<string, NodeShape>();
const previousShapes = new WeakMap<object, NodeShape>();
const shapeParams = new Map<string, string[] | null>();
const CACHE_LIMIT = 256;
function remember(map: Map<string, NodeShape>, key: string, value: NodeShape) {
  map.delete(key);
  map.set(key, value);
  while (map.size > CACHE_LIMIT) map.delete(map.keys().next().value!);
}
const listeners = new Set<() => void>();
let version = 0;

function keyOf(node: ShapeNode): string {
  return `${node.type}|${JSON.stringify(paramsOf(node))}`;
}

function paramsOf(node: ShapeNode): Record<string, unknown> {
  const keys = shapeParams.get(node.type);
  return keys ? Object.fromEntries(keys.map((key) => [key, node.params?.[key]])) : node.params ?? {};
}

/** The server's answer for this node's CURRENT params, when it has arrived. */
export function cachedShape(node: ShapeNode): NodeShape | undefined {
  return cache.get(keyOf(node)) ?? previousShapes.get(node);
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
  const lastShapes = useRef(new Map<string, NodeShape>());
  for (const spec of catalog?.nodes ?? []) shapeParams.set(spec.key, spec.shape_params ?? null);
  for (const node of nodes) {
    const previous = node.id ? lastShapes.current.get(`${node.type}|${node.id}`) : undefined;
    if (previous) previousShapes.set(node, previous);
  }
  const requested = JSON.stringify(nodes.filter((node) => isDynamic(node, catalog)).map((node) => ({ id: node.id, type: node.type, params: paramsOf(node) })));
  const [settled, setSettled] = useState(requested);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(requested), 200);
    return () => clearTimeout(timer);
  }, [requested]);
  const dynamic = useMemo(() => JSON.parse(settled) as ShapeNode[], [settled]);
  const results = useQueries({
    queries: dynamic.map((node) => ({
      queryKey: ["automation-node-shape", node.type, JSON.stringify(node.params ?? {})],
      queryFn: () =>
        api.post<NodeShape>(apiAutomationNodeShapePath(node.type), { params: node.params ?? {} }),
      staleTime: Infinity,
      gcTime: 60_000,
    })),
  });
  useEffect(() => {
    let changed = false;
    results.forEach((result, index) => {
      const node = dynamic[index];
      if (!node || !result.data) return;
      const key = keyOf(node);
      if (node.id) remember(lastShapes.current, `${node.type}|${node.id}`, result.data);
      if (cache.get(key) === result.data) return;
      remember(cache, key, result.data);
      changed = true;
    });
    if (changed) {
      version += 1;
      for (const listener of listeners) listener();
    }
  });
  return useShapeVersion();
}
