import { api, type QuerySource } from "@radd/plugin-sdk";
import type { Label } from "./types";
const meta = { entities: ["label", "role", "member"] };
/** The whole catalog as an ordinary query — for host pages that read it directly (settings,
 * filters). Plugins that must not depend on this package read the catalog
 * through the SDK query-source registry instead. */
export const labelsQuery = () => ({
  queryKey: ["labels"] as const, meta, staleTime: 60_000,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<Label[]>("/labels", { signal }),
});
/** Declarative data contract; consumers receive availability independently of results. */
export const catalogSource: QuerySource<Label[]> = {
  key: "labels.catalog", meta,
  fetch: (_args, signal) => labelsQuery().queryFn({ signal }),
};
