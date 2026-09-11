import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";

export interface ProvisioningReferences { roles: Record<string, string>; projects: Record<string, string>; teams: Record<string, string> }
export const provisioningReferencesQuery = (roleIds: string[], projectIds: string[], teamIds: string[]) => {
  const body = { role_ids: [...new Set(roleIds)].sort(), project_ids: [...new Set(projectIds)].sort(), team_ids: [...new Set(teamIds)].sort() };
  return queryOptions({
    queryKey: ["sso-provisioning-references", body],
    meta: entityMeta(Entity.role, Entity.project, Entity.team),
    queryFn: ({ signal }) => api.post<ProvisioningReferences>("/sso/provisioning-references", body, { signal }),
    enabled: Boolean(body.role_ids.length + body.project_ids.length + body.team_ids.length),
  });
};
