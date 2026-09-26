import { api, type QuerySource } from "@radd/plugin-sdk";
import type { Label } from "./types";
const meta = { entities: ["label", "role", "member"] };
/** The catalog as a plain query (host pages); plugins read it through the query source below. */
export const labelsQuery = () => ({
  queryKey: ["labels"] as const, meta, staleTime: 60_000,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<Label[]>("/labels", { signal }),
});
/** Declarative data contract; consumers receive availability independently of results. */
export const catalogSource: QuerySource<Label[]> = {
  key: "labels.catalog", meta,
  fetch: (_args, signal) => labelsQuery().queryFn({ signal }),
};
