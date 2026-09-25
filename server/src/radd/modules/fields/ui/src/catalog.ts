import { api, type QuerySource } from "@radd/plugin-sdk";
import type { FieldDef } from "./types";
const meta = { entities: ["field", "project", "role", "team", "group", "member", "accessGrant"] };
/** Compatibility query for consumers still awaiting owner migration. */
export const fieldsQuery = () => ({
  queryKey: ["fields"] as const, meta, staleTime: 60_000,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<FieldDef[]>("/fields", { signal }),
});
/** Declarative data contract; consumers receive availability independently of results. */
export const catalogSource: QuerySource<FieldDef[]> = {
  key: "fields.catalog", meta,
  fetch: (_args, signal) => fieldsQuery().queryFn({ signal }),
};
