/** The scripts plugin (RADD-1269). */
import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import type { ScriptInterpreter, ScriptPackage } from "../types";

export const scriptKeys = {
  interpreter: ["scripts", "interpreter"] as const,
  packages: ["scripts", "packages"] as const,
};

export const scriptInterpreterQuery = queryOptions({
  queryKey: scriptKeys.interpreter,
  queryFn: ({ signal }) => api.get<ScriptInterpreter>(`${ApiPath.scripts}/interpreter`, { signal }),
  retry: false,
});

export const scriptPackagesQuery = queryOptions({
  queryKey: scriptKeys.packages,
  queryFn: ({ signal }) => api.get<ScriptPackage[]>(`${ApiPath.scripts}/packages`, { signal }),
  retry: false,
});
