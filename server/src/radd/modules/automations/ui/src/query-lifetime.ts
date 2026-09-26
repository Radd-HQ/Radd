import { useQuery } from "@tanstack/react-query";
import { useCapabilities } from "@radd/plugin-sdk";

/** An Automations read. Keyed by the loaded plugin set, because the catalog, shapes and samples
 * are a function of which plugins are loaded; everything else is an ordinary shared query
 * (RADD-1373 — it used to carry a per-mount identity and never cache). A failed refresh hides
 * what it had: a revoked permission must not keep showing rules. */
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
