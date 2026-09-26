import { useQuery } from "@tanstack/react-query";
import { api, useCapabilities } from "@radd/plugin-sdk";

/** The one convention every connector's admin API follows (`<provider>/admin_router.py`). */
export function hostPaths(provider: string) {
  const base = `/${provider}`;
  const id = (value: string) => encodeURIComponent(value);
  return {
    connections: `${base}/connections`,
    repos: `${base}/repos`,
    connection: (value: string) => `${base}/connections/${id(value)}`,
    connectionTest: (value: string) => `${base}/connections/${id(value)}/test`,
    repo: (value: string) => `${base}/repos/${id(value)}`,
    backfill: (value: string) => `${base}/repos/${id(value)}/backfill`,
  };
}

/** Cache tags a connector's rows carry, as the realtime hub names them. */
export const hostEntities = (provider: string) => [`${provider}Connection`, `${provider}Repo`];

/** Audited entity types for the page's "Change history" footer (spec 123). */
export const historyEntities = (provider: string) => [`${provider}_connection`, `${provider}_repo`, "vcs_user_link"];

/** A read about one connector, fetched only while that connector is loaded.
 * A failed refresh (a revoked permission answers 403) hides the rows it had:
 * credentials and identities are not something to keep showing after a denial. */
export function useVcsList<T>(provider: string, key: string[], path: string, entities: string[]) {
  const caps = useCapabilities();
  const result = useQuery<T>({
    queryKey: ["vcs", provider, ...key],
    enabled: caps?.plugins.includes(provider) === true,
    meta: { entities },
    queryFn: ({ signal }) => api.get<T>(path, { signal }),
  });
  return { ...result, data: result.isError ? undefined : result.data };
}

export const useHostQuery = <T,>(provider: string, what: "connections" | "repos") =>
  useVcsList<T>(provider, [what], hostPaths(provider)[what], hostEntities(provider));
