import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import type { AuditEntry, AuditCatalog, AuditSourceValue } from "./types";
export interface AuditParams {
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


/** Observer-owned keys prevent stale authorization/results surviving an unmount or activation. */
const ACCESS_META = {entities: ["project", "role", "team", "group", "member", "accessGrant"]};
export function useAudit(params: AuditParams, revision: string, enabled = true) {
  const session = useId();
  return useQuery({queryKey: ["audit", "rows", session, revision, auditWire(params), enabled], enabled,
    gcTime: 0, staleTime: 0, retry: false, meta: {...ACCESS_META, entities: [...ACCESS_META.entities, "field"]},
    queryFn: ({signal}) => api.get<AuditEntry[]>("/audit", {signal, query: auditWire(params)}),
  });
}
export function useAuditCatalog(revision: string) {
  const session = useId();
  return useQuery({queryKey: ["audit", "catalog", session, revision], gcTime: 0, staleTime: 0, retry: false,
    queryFn: ({signal}) => api.get<AuditCatalog>("/audit/catalog", {signal}),
  });
}
export function useAuditAccess(projectId?: string, enabled = true) {
  const session = useId();
  const result = useQuery({queryKey: ["audit", "access", session, projectId ?? "", enabled], enabled, gcTime: 0, staleTime: 0, retry: false, meta: ACCESS_META,
    queryFn: ({signal}) => api.get<{allowed: boolean; instance_wide: boolean}>("/audit/access", {signal, query: {project_id: projectId}}),
  });
  return {...result, data: !enabled || result.isError ? undefined : result.data};
}
