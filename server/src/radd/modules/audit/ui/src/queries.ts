import { useQuery } from "@tanstack/react-query";
import { api, Entity } from "@radd/plugin-sdk";
import type { AuditEntry, AuditCatalog, AuditSourceValue } from "./types";
interface AuditParams {
  /** Constrains the read to one project — REQUIRED for anyone but an instance admin. */
  projectId?: string;
  entityType?: string;
  entityId?: string;
  actorId?: string;
  /** Rows whose diff touched this field (`assignee`, `permissions`…). */
  changedField?: string;
  source?: AuditSourceValue | "";
  /** ISO dates (inclusive day bounds are applied by the caller). */
  start?: string;
  end?: string;
  /** Trigram free text over the event, the entity and the changed values (spec 123). */
  q?: string;
  includeNoise?: boolean;
  limit?: number;
  offset?: number;
}

const auditWire = (params: AuditParams): Record<string, string | undefined> => ({
  project_id: params.projectId || undefined,
  entity_type: params.entityType || undefined,
  entity_id: params.entityId || undefined,
  actor_id: params.actorId || undefined,
  changed_field: params.changedField || undefined,
  source: params.source || undefined,
  start: params.start || undefined,
  end: params.end || undefined,
  q: params.q || undefined,
  include_noise: params.includeNoise ? "true" : undefined,
  limit: String(params.limit ?? 100),
  offset: String(params.offset ?? 0),
});


/** Access and rows refresh when anything that decides who may read them changes. A failed read
 * hides what it had (a revoked scope must not keep showing rows); otherwise these are ordinary
 * shared queries (RADD-1373 — they carried a per-mount identity and never cached). */
const ACCESS_META = {entities: [Entity.project, Entity.role, Entity.team, Entity.group, Entity.member, Entity.accessGrant]};
export function useAudit(params: AuditParams, revision: string, enabled = true) {
  return useQuery({queryKey: ["audit", "rows", revision, auditWire(params), enabled], enabled,
    meta: {...ACCESS_META, entities: [...ACCESS_META.entities, Entity.field]},
    queryFn: ({signal}) => api.get<AuditEntry[]>("/audit", {signal, query: auditWire(params)}),
  });
}
export function useAuditCatalog(revision: string) {
  return useQuery({queryKey: ["audit", "catalog", revision], staleTime: 5 * 60_000,
    queryFn: ({signal}) => api.get<AuditCatalog>("/audit/catalog", {signal}),
  });
}
export function useAuditAccess(projectId?: string, enabled = true) {
  const result = useQuery({queryKey: ["audit", "access", projectId ?? "", enabled], enabled, staleTime: 30_000, meta: ACCESS_META,
    queryFn: ({signal}) => api.get<{allowed: boolean; instance_wide: boolean}>("/audit/access", {signal, query: {project_id: projectId}}),
  });
  return {...result, data: !enabled || result.isError ? undefined : result.data};
}
