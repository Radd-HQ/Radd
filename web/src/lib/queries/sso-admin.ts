/** SSO provider registry (spec 110) — Settings → Sign-in. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import { queryKeys } from "./shared";
import type { SsoKindInfo, SsoProviderRead } from "../types";

/** Configured providers, env-seeded ones included. Secrets are never in the response. */
export const ssoProvidersQuery = () =>
  queryOptions({
    queryKey: queryKeys.ssoProviders,
    queryFn: () => api.get<SsoProviderRead[]>(ApiPath.ssoProviders),
    staleTime: 30_000,
  });

/** Discovery defaults per provider kind — what the "add" form prefills itself with. */
export const ssoKindsQuery = () =>
  queryOptions({
    queryKey: queryKeys.ssoKinds,
    queryFn: () => api.get<SsoKindInfo[]>(ApiPath.ssoKinds),
    staleTime: Infinity, // a static server-side catalog
  });
