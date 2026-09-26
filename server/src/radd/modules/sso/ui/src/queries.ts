import { queryOptions } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import type { ProvisioningReferences, SsoKindInfo, SsoProviderRead } from "./types";

/** The provider registry's admin endpoints (spec 110) — instance admins only. */
export const PROVIDERS_PATH = "/sso/providers";
const KINDS_PATH = "/sso/kinds";
const REFERENCES_PATH = "/sso/provisioning-references";
export const providerPath = (providerId: string) => `${PROVIDERS_PATH}/${providerId}`;
export const providerTestPath = (providerId: string) => `${providerPath(providerId)}/test`;

export const providersKey = ["sso", "providers"] as const;

/** Configured providers, env-seeded ones included. Secrets are never in the response. */
export const ssoProvidersQuery = () =>
  queryOptions({
    queryKey: providersKey,
    queryFn: ({ signal }) => api.get<SsoProviderRead[]>(PROVIDERS_PATH, { signal }),
    staleTime: 30_000,
  });

/** Discovery defaults per provider kind — what the "add" form prefills itself with. */
export const ssoKindsQuery = () =>
  queryOptions({
    queryKey: ["sso", "kinds"] as const,
    queryFn: ({ signal }) => api.get<SsoKindInfo[]>(KINDS_PATH, { signal }),
    staleTime: Infinity, // a static server-side catalog
  });

/** Names for the role/project/team ids a starting-access rule stores. Tagged with the entities
 *  it names, so a rename anywhere refreshes the labels. */
export const provisioningReferencesQuery = (roleIds: string[], projectIds: string[], teamIds: string[]) => {
  const body = {
    role_ids: [...new Set(roleIds)].sort(),
    project_ids: [...new Set(projectIds)].sort(),
    team_ids: [...new Set(teamIds)].sort(),
  };
  return queryOptions({
    queryKey: ["sso", "provisioning-references", body] as const,
    meta: { entities: ["role", "project", "team"] },
    queryFn: ({ signal }) => api.post<ProvisioningReferences>(REFERENCES_PATH, body, { signal }),
    enabled: Boolean(body.role_ids.length + body.project_ids.length + body.team_ids.length),
  });
};
