import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ErrorText } from "../ErrorText";

export function TeamAccessImpact({ teamId }: { teamId: string }) {
  const impact = useQuery({
    queryKey: ["team-access-impact", teamId],
    queryFn: () => api.get<{roles: number; global_roles: number; projects: number; spaces: number; resource_rules: {label: string; count: number}[]}>(`/teams/${teamId}/access-impact`),
    staleTime: 0,
  });
  if (impact.isPending) return <p className="text-xs text-fg-muted">Checking membership access…</p>;
  if (impact.isError) return <ErrorText error={impact.error} />;
  const data = impact.data;
  return <div className="mb-2 rounded border border-subtle p-2 text-xs text-fg-muted">
    <p>Membership carries {data.roles} role grant{data.roles === 1 ? "" : "s"}: {data.global_roles} instance-wide, across {data.projects} selected projects and {data.spaces} wiki spaces.</p>
    {data.resource_rules.length > 0 && <p>Resource rules: {data.resource_rules.map(r => `${r.count} ${r.label.toLowerCase()}`).join(", ")}. These can allow or deny access.</p>}
    <p>New members receive this access; removing a member leaves any access they hold through other sources.</p>
  </div>;
}
