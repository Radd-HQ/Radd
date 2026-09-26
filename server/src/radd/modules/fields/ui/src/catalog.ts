import { api, type QuerySource } from "@radd/plugin-sdk";
import type { FieldDef } from "./types";
const meta = { entities: ["field", "project", "role", "team", "group", "member", "accessGrant"] };
/** The catalog as a plain query (host pages); plugins read it through the query source below. */
export const fieldsQuery = () => ({
  queryKey: ["fields"] as const, meta, staleTime: 60_000,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<FieldDef[]>("/fields", { signal }),
});
/** Declarative data contract; consumers receive availability independently of results. */
export const catalogSource: QuerySource<FieldDef[]> = {
  key: "fields.catalog", meta,
  fetch: (_args, signal) => fieldsQuery().queryFn({ signal }),
};
