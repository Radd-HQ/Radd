/** Server-computed ports and outputs for nodes whose shape depends on their params. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { api, useCapabilities } from "@radd/plugin-sdk";
import type { AutomationCatalog } from "./types";
import { shapeKey, type NodeShape, type NodeShapes, type ShapeNode } from "./shape-contract";

type Request = { key: string; type: string; params: Record<string, unknown> };
const requestKey = (node: Request) => JSON.stringify([node.type, node.params]);

/** One cached answer per (loaded plugins — a withdrawn provider's node has no shape — type, params),
 * debounced; a node keeps its last ports while a new answer is in flight. A refused or failed read
 * offers no ports. */
export function useNodeShapes(nodes: ShapeNode[], catalog: AutomationCatalog | undefined, enabled = true): NodeShapes {
  const capabilities = useCapabilities();
  const plugins = capabilities?.plugins ?? [];
  const loaded = plugins.join(",");
  // Bundled with the host and registered only while the server loads automations: no gate on the
  // manifest, which would keep every dynamic node port-less until it answered (RADD-1462).
  const active = enabled;
  const requested = useMemo(() => JSON.stringify(active ? nodes.flatMap((node): Request[] => {
    const spec = catalog?.nodes.find((entry) => entry.key === node.type);
    if (!spec || (!spec.dynamic_ports && !spec.dynamic_outputs)) return [];
    // A retained catalog may still describe a provider withdrawn this render.
    if (spec.plugin && !loaded.split(",").includes(spec.plugin)) return [];
    const params = spec.shape_params
      ? Object.fromEntries(spec.shape_params.map((key) => [key, node.params[key]]))
      : node.params;
    return [{ key: shapeKey(node), type: node.type, params }];
  }) : []), [active, nodes, catalog, loaded]);
  const [settled, setSettled] = useState(requested);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(requested), 200);
    return () => clearTimeout(timer);
  }, [requested]);
  const current = JSON.parse(requested) as Request[];
  const dynamic = useMemo(
    () => [...new Map((JSON.parse(settled) as Request[]).map((node) => [requestKey(node), node])).values()],
    [settled],
  );
  const results = useQueries({ queries: dynamic.map((node) => ({
    queryKey: ["automations", "node-shape", loaded, node.type, JSON.stringify(node.params)],
    queryFn: ({ signal }: { signal: AbortSignal }) => api.post<NodeShape>(
      `/automations/nodes/${encodeURIComponent(node.type)}/shape`, { params: node.params }, { signal },
    ),
    staleTime: Infinity,
  })) });
  const answers = new Map<string, { ok: boolean; shape?: NodeShape }>();
  results.forEach((result, index) => {
    const node = dynamic[index];
    if (node && (result.isSuccess || result.isError)) answers.set(requestKey(node), { ok: result.isSuccess, shape: result.data });
  });
  const last = useRef<Record<string, NodeShape>>({});
  const shapes: Record<string, NodeShape> = {};
  for (const node of current) {
    const answer = answers.get(requestKey(node));
    if (answer?.ok && answer.shape) shapes[node.key] = answer.shape;
    else if (!answer && last.current[node.key]) shapes[node.key] = last.current[node.key];
  }
  last.current = shapes;
  return shapes;
}
