import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, invalidateEntities } from "@radd/plugin-sdk";
import { AiEntity, AiPath, type AiPreset, type AiProviderRead, type AiRoleRead } from "./types";

/** Configured providers, env-seeded ones included. Keys are never in the response. */
export const useAiProviders = () =>
  useQuery({
    queryKey: ["ai", "providers"],
    meta: { entities: [AiEntity.provider] },
    queryFn: ({ signal }) => api.get<AiProviderRead[]>(AiPath.providers, { signal }),
    staleTime: 30_000,
  });

/** Role → provider assignments. A role with no row is unassigned (its features stay dormant). */
export const useAiRoles = () =>
  useQuery({
    queryKey: ["ai", "roles"],
    meta: { entities: [AiEntity.role] },
    queryFn: ({ signal }) => api.get<AiRoleRead[]>(AiPath.roles, { signal }),
    staleTime: 30_000,
  });

/** Preset prompts — the admin-curated editor-action library. */
export const useAiPresets = () =>
  useQuery({
    queryKey: ["ai", "presets"],
    meta: { entities: [AiEntity.preset] },
    queryFn: ({ signal }) => api.get<AiPreset[]>(AiPath.presets, { signal }),
    staleTime: 30_000,
  });

/** Refresh everything tagged with these AI entities — this page's lists and the AI gate. */
export function useInvalidateAi() {
  const queryClient = useQueryClient();
  return (...entities: string[]) => void invalidateEntities(queryClient, ...entities);
}
