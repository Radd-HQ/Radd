/** The scripts plugin (RADD-1269). */
import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import type { Script, ScriptInterpreter, ScriptPackage, ScriptSummary, ScriptVersion } from "../types";

export const scriptKeys = {
  all: ["scripts"] as const,
  interpreter: ["scripts", "interpreter"] as const,
  packages: ["scripts", "packages"] as const,
  one: (id: string) => ["scripts", "one", id] as const,
  versions: (id: string) => ["scripts", "one", id, "versions"] as const,
};

export const scriptsQuery = queryOptions({
  queryKey: scriptKeys.all,
  queryFn: ({ signal }) => api.get<ScriptSummary[]>(ApiPath.scripts, { signal }),
  retry: false,
});

export const scriptQuery = (id: string) =>
  queryOptions({
    queryKey: scriptKeys.one(id),
    queryFn: ({ signal }) => api.get<Script>(`${ApiPath.scripts}/${id}`, { signal }),
    retry: false,
  });

export const scriptVersionsQuery = (id: string) =>
  queryOptions({
    queryKey: scriptKeys.versions(id),
    queryFn: ({ signal }) => api.get<ScriptVersion[]>(`${ApiPath.scripts}/${id}/versions`, { signal }),
    retry: false,
  });

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
