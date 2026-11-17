import { api, type QuerySource, Entity } from "@radd/plugin-sdk";
import type { FieldDef } from "./types";
const meta = { entities: [Entity.field, Entity.project, Entity.role, Entity.team, Entity.group, Entity.member, Entity.accessGrant] };
/** The catalog as a plain query (host pages); plugins read it through the query source below. */
/** With a project: only the fields in scope for it (RADD-1551) — what an issue
 *  page needs, a fifth of the catalog on an instance with many project-scoped fields. */
export const fieldsQuery = (projectId?: string) => ({
  queryKey: (projectId ? ["fields", { projectId }] : ["fields"]) as readonly unknown[], meta, staleTime: 60_000,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api.get<FieldDef[]>(projectId ? `/fields?project_id=${projectId}` : "/fields", { signal }),
});
/** Declarative data contract; consumers receive availability independently of results. */
export const catalogSource: QuerySource<FieldDef[]> = {
  key: "fields.catalog", meta,
  fetch: (_args, signal) => fieldsQuery().queryFn({ signal }),
};
