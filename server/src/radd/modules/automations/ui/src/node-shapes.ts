/** Server-computed ports and outputs, scoped to a mounted graph and live catalog. */
import { useEffect, useId, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { api, useCapabilities } from "@radd/plugin-sdk";
import type { AutomationCatalog } from "./types";
import { shapeKey, type NodeShape, type NodeShapes, type ShapeNode } from "./shape-contract";

export function useNodeShapes(nodes: ShapeNode[], catalog: AutomationCatalog | undefined, enabled = true): NodeShapes {
  const instance = useId();
  const capabilities = useCapabilities();
  const active = enabled && (capabilities?.plugins.includes("automations") ?? false);
  // Invalidate even when a replacement catalog has the same number of entries.
  // A capability change also invalidates retained catalogs while they refetch.
  const scope = JSON.stringify([active, capabilities?.plugins, catalog]);
  const requested = JSON.stringify(active ? nodes.flatMap(node => {
    const spec = catalog?.nodes.find(entry => entry.key === node.type);
    if (!spec || (!spec.dynamic_ports && !spec.dynamic_outputs)) return [];
    // A retained catalog may still describe a provider withdrawn this render.
    if (spec.plugin && !capabilities?.plugins.includes(spec.plugin)) return [];
    const params = spec.shape_params
      ? Object.fromEntries(spec.shape_params.map(key => [key, node.params[key]]))
      : node.params;
    return [{ key: shapeKey(node), type: node.type, params }];
  }) : []);
  const [settled, setSettled] = useState({ scope, requested });
  useEffect(() => {
    const timer = setTimeout(() => setSettled({ scope, requested }), 200);
    return () => clearTimeout(timer);
  }, [scope, requested]);
  // Withdrawal is immediate; only parameter edits are debounced. Never send an
  // old provider request while waiting for the debounce timer to catch up.
  const selected = settled.scope === scope ? settled.requested : requested;
  type Request = { key: string; type: string; params: Record<string, unknown> };
  const requestKey = (node: Request) => JSON.stringify([node.type, node.params]);
  const current = JSON.parse(requested) as Request[];
  const dynamic = useMemo(() => {
    const currentRequests = new Set((JSON.parse(requested) as Request[]).map(requestKey));
    // Deduplicate equal shapes, and stop a removed/edited node's in-flight
    // request immediately rather than waiting for the debounce timer.
    return [...new Map((JSON.parse(selected) as Request[])
      .filter(node => currentRequests.has(requestKey(node)))
      .map(node => [requestKey(node), node])).values()];
  }, [selected, requested]);
  const results = useQueries({ queries: dynamic.map(node => ({
    queryKey: ["automation-node-shape", instance, scope, node.type, JSON.stringify(node.params)],
    queryFn: ({ signal }: { signal: AbortSignal }) => api.post<NodeShape>(
      `/automations/nodes/${encodeURIComponent(node.type)}/shape`, { params: node.params }, { signal },
    ),
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  })) });
  const shapes: Record<string, NodeShape> = {};
  results.forEach((result, index) => {
    const node = dynamic[index];
    // Old params and failed/refused reads must not offer misleading ports/tokens.
    if (node && result.isSuccess) for (const candidate of current) {
      if (requestKey(candidate) === requestKey(node)) shapes[candidate.key] = result.data;
    }
  });
  return shapes;
}
