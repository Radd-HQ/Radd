/** The scripts plugin (RADD-1269). */
import { queryOptions } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import type { ScriptInterpreter, ScriptPackage } from "./types";

export const SCRIPTS_API = "/scripts";

export const scriptKeys = {
  interpreter: ["scripts", "interpreter"] as const,
  packages: ["scripts", "packages"] as const,
};

export const scriptInterpreterQuery = queryOptions({
  queryKey: scriptKeys.interpreter,
  queryFn: ({ signal }) => api.get<ScriptInterpreter>(`${SCRIPTS_API}/interpreter`, { signal }),
  retry: false,
  staleTime: 0,
  gcTime: 0,
});

export const scriptPackagesQuery = queryOptions({
  queryKey: scriptKeys.packages,
  queryFn: ({ signal }) => api.get<ScriptPackage[]>(`${SCRIPTS_API}/packages`, { signal }),
  retry: false,
  staleTime: 0,
  gcTime: 0,
});
