import { useQuery } from "@tanstack/react-query";
import { useCapabilities } from "@radd/plugin-sdk";

/** Keyed by the loaded plugin set (catalog, shapes and samples depend on it). A failed refresh hides its
 * data: a revoked permission must not keep showing rules. */
export function useAutomationQuery<T>(options: {
  queryKey: readonly unknown[];
  queryFn?: (context: {signal: AbortSignal}) => Promise<T>;
  enabled?: boolean;
  refetchInterval?: number;
  staleTime?: number;
}) {
  const caps = useCapabilities();
  const plugins = caps?.plugins?.join(",") ?? "";
  const enabled = caps?.plugins?.includes("automations") === true && options.enabled !== false;
  const result = useQuery<T>({
    queryKey: [...options.queryKey, plugins],
    enabled,
    staleTime: options.staleTime ?? 0,
    meta: {entities: ["automation", "role"]},
    ...(typeof options.refetchInterval === "number" ? {refetchInterval: options.refetchInterval} : {}),
    queryFn: context => {
      if (!enabled || typeof options.queryFn !== "function") throw new Error("Automations is unavailable");
      return options.queryFn(context);
    },
  });
  return {...result, data: enabled && !result.isError ? result.data : undefined};
}
