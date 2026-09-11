/** AI provider registry (spec 101): providers, role assignments, preset prompts. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import { queryKeys } from "./shared";
import type { AiPreset, AiProviderRead, AiRoleRead } from "../types";

/** Configured providers, env-seeded ones included. Keys are never in the response. */
export const aiProvidersQuery = () =>
  queryOptions({
    queryKey: queryKeys.aiProviders,
    queryFn: ({ signal }) => api.get<AiProviderRead[]>(ApiPath.aiProviders, { signal }),
    staleTime: 30_000,
  });

/** Role → provider assignments. A role with no row is unassigned (its features stay dormant). */
export const aiRolesQuery = () =>
  queryOptions({
    queryKey: queryKeys.aiRoles,
    queryFn: ({ signal }) => api.get<AiRoleRead[]>(ApiPath.aiRoles, { signal }),
    staleTime: 30_000,
  });

/** Preset prompts — the admin-curated editor-action library (spec 103 consumes it). */
export const aiPresetsQuery = () =>
  queryOptions({
    queryKey: queryKeys.aiPresets,
    queryFn: ({ signal }) => api.get<AiPreset[]>(ApiPath.aiPresets, { signal }),
    staleTime: 30_000,
  });

/** The signed-in user's server-side preferences dict (spec 94; PUT shallow-merges). */
export const mePreferencesQuery = () =>
  queryOptions({
    queryKey: queryKeys.mePreferences,
    queryFn: ({ signal }) => api.get<Record<string, unknown>>(ApiPath.mePreferences, { signal }),
    staleTime: 60_000,
  });
