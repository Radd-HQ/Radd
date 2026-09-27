/**
 * The query-key prefixes the host and the SDK both spell (RADD-1467). A key array is a wire
 * constant with no compiler behind it — the `["plugin-query", owner]` the loader drops must be
 * the prefix `sourceQuery` builds — so each is named once here and imported everywhere.
 */
export const QueryKeyPrefix = {
  /** `GET /capabilities` — the manifest the host draws itself from; `useCapabilities` shares it. */
  capabilities: "capabilities",
  /** A contributed query source's results: `[pluginQuery, owner, generation, key, args]`. */
  pluginQuery: "plugin-query",
  /** A contributed command source's list: `[pluginCommands, owner, generation, source, context]`. */
  pluginCommands: "plugin-commands",
} as const;

/** The manifest's whole key — one entry, so it is the prefix as well. */
export const capabilitiesQueryKey = [QueryKeyPrefix.capabilities] as const;
