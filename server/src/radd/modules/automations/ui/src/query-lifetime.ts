import { createContext, createElement, useContext, useId, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useCapabilities } from "@radd/plugin-sdk";

const Scope = createContext<string | null>(null);
export function AutomationScope({children}: {children: ReactNode}) {
  const session = useId();
  return createElement(Scope.Provider, {value: session}, children);
}
/** A mounted editor owns its reads. Changing the active plugin catalog replaces
 * observers and cancels unused requests; reopening never revives old permission data. */
export function useAutomationQuery<T>(options: {
  queryKey: readonly unknown[];
  queryFn?: (context: {signal: AbortSignal}) => Promise<T>;
  enabled?: boolean;
  refetchInterval?: number;
  staleTime?: number;
}) {
  const localSession = useId();
  const session = useContext(Scope) ?? localSession;
  const caps = useCapabilities();
  const revision = JSON.stringify([caps?.plugins, caps?.remotes]);
  const enabled = caps?.plugins?.includes("automations") === true && options.enabled !== false;
  const result = useQuery<T>({
    queryKey: [...options.queryKey, session, revision, enabled],
    enabled, gcTime: 0, staleTime: options.staleTime ?? 0, retry: false,
    meta: {entities: ["automation", "role", "member", "team", "group", "accessGrant"]},
    ...(typeof options.refetchInterval === "number" ? {refetchInterval: options.refetchInterval} : {}),
    queryFn: context => {
      if (!enabled || typeof options.queryFn !== "function") throw new Error("Automations is unavailable");
      return options.queryFn(context);
    },
  });
  return {...result, data: enabled && !result.isError ? result.data : undefined};
}
