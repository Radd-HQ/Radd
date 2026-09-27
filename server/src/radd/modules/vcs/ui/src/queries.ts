import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, useCapabilities, type CacheTag } from "@radd/plugin-sdk";
import type { VcsConnector } from "./types";

/** The connector plugins loaded now, one tab each (`GET /vcs/connectors`). Keyed on
 * the enabled plugins, so enabling or disabling one asks again; a connector the
 * capabilities stopped listing leaves at once rather than after the answer.
 * `settling` = a new answer is on its way and the previous one is showing. */
export function useConnectors(enabled: boolean) {
  const caps = useCapabilities();
  const loaded = caps?.plugins ?? [];
  const result = useQuery<VcsConnector[]>({
    queryKey: ["vcs", "connectors", loaded.join(",")],
    enabled: enabled && caps !== undefined,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => api.get<VcsConnector[]>("/vcs/connectors", { signal }),
  });
  const data = result.isError ? undefined : result.data?.filter((connector) => loaded.includes(connector.provider));
  return { ...result, data, settling: result.isPlaceholderData };
}

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
export function useVcsList<T>(provider: string, key: string[], path: string, entities: CacheTag[]) {
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
