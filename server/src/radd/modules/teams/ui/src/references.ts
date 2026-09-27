import { api, Entity } from "@radd/plugin-sdk";
export const TEAM_REFERENCE_PAGE_SIZE = 50;
interface TeamReference { id: string; name: string; member_count: number | null }
/** Names/counts only; bounded by callers, permission-enforced by Teams. */
export const teamReferencesQuery = (ids: string[], includeCounts = false) => {
  const identifiers = [...new Set(ids)].sort();
  return {
    queryKey: ["teams", "references", identifiers, includeCounts] as const,
    meta: { entities: [Entity.team, Entity.role, Entity.member, Entity.group] },
    enabled: identifiers.length > 0,
    queryFn: ({ signal }: { signal: AbortSignal }) => {
      const query = new URLSearchParams({ include_counts: String(includeCounts) });
      identifiers.forEach(id => query.append("ids", id));
      return api.get<TeamReference[]>(`/teams/references?${query}`, { signal });
    },
  };
};
