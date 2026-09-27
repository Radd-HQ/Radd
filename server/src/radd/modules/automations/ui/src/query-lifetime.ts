import { useQuery } from "@tanstack/react-query";
import { Entity, useCapabilities } from "@radd/plugin-sdk";

/** Keyed by the loaded plugin set (catalog, shapes and samples depend on it). A failed refresh hides its
 * data: a revoked permission must not keep showing rules. This UI is bundled with the host and registered
 * only while the server loads automations, so there is nothing to gate on: a capabilities check here
 * blanked every page until the manifest answered (RADD-1462). Lifetimes are the SDK's defaults; a
 * surface that needs fresher data says so per query. */
export function useAutomationQuery<T>(options: {
  queryKey: readonly unknown[];
  queryFn?: (context: {signal: AbortSignal}) => Promise<T>;
  enabled?: boolean;
  refetchInterval?: number;
  staleTime?: number;
}) {
  const caps = useCapabilities();
  const plugins = caps?.plugins?.join(",") ?? "";
  const enabled = options.enabled !== false;
  const result = useQuery<T>({
    queryKey: [...options.queryKey, plugins],
    enabled,
    ...(typeof options.staleTime === "number" ? {staleTime: options.staleTime} : {}),
    meta: {entities: [Entity.automation, Entity.role]},
    ...(typeof options.refetchInterval === "number" ? {refetchInterval: options.refetchInterval} : {}),
    queryFn: context => {
      if (!enabled || typeof options.queryFn !== "function") throw new Error("Automations is unavailable");
      return options.queryFn(context);
    },
  });
  return {...result, data: enabled && !result.isError ? result.data : undefined};
}
