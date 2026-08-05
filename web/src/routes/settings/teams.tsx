import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Plus, UsersRound } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { queryKeys, teamsQuery } from "../../lib/queries";
import { Permission, type Team, type TeamCreate } from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TeamPanel } from "../../components/settings/TeamPanel";
import { QueryError } from "../../components/QueryError";

export function TeamsSettingsPage() {
  const perms = usePermissions();
  // Spec 87: creating a team is still a global act; administering one is not —
  // each row carries its own `can_manage` (owner/manager/atom-holder).
  const canCreate = perms.global(Permission.teamCreate);
  const teams = useQuery(teamsQuery());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const all = teams.data ?? [];
  const search = useListFilter(all, (team) => [team.name]);
  const list = search.filtered;

  return (
    <SettingsPage
      title="Teams"
      description="Group people, then attach a team to projects with a role — that's what grants project access. A team linked to an AD group takes its members from the directory."
    >
      {teams.isPending ? (
        <TableSkeleton rows={3} />
      ) : teams.isError ? (
        <QueryError label="teams" error={teams.error} />
      ) : (
        <>
          {all.length === 0 ? (
            <EmptyState icon={UsersRound} message="No teams yet." />
          ) : (
            <>
              {all.length > 8 && (
                <ListSearchInput
                  className="mb-3"
                  value={search.filter}
                  onChange={search.setFilter}
                  placeholder="Filter teams by name…"
                  total={all.length}
                  matched={list.length}
                  noun="teams"
                />
              )}
              {list.length === 0 ? (
                <EmptyState
                  icon={UsersRound}
                  message={`No teams match “${search.filter.trim()}”.`}
                />
              ) : (
                <ul className="rounded-lg border border-subtle">
                  {list.map((team) => {
                    const expanded = expandedId === team.id;
                    return (
                      <li key={team.id} className="border-b border-subtle/60 last:border-b-0">
                        <button
                          type="button"
                          onClick={() => setExpandedId(expanded ? null : team.id)}
                          aria-expanded={expanded}
                          className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-surface/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus cursor-pointer"
                        >
                          {expanded ? (
                            <ChevronDown size={14} className="text-fg-muted" aria-hidden />
                          ) : (
                            <ChevronRight size={14} className="text-fg-muted" aria-hidden />
                          )}
                          <span className="text-[13px] font-medium text-heading">{team.name}</span>
                          <span className="ml-auto text-xs text-fg-faint">
                            {new Date(team.created_at).toLocaleDateString()}
                          </span>
                        </button>
                        {expanded && <TeamPanel team={team} />}
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
          {canCreate && (
            <NewTeamForm onCreated={(team) => setExpandedId(team.id)} />
          )}
        </>
      )}
    </SettingsPage>
  );
}

function NewTeamForm({ onCreated }: { onCreated: (team: Team) => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const createTeam = useMutation({
    mutationFn: (body: TeamCreate) => api.post<Team>(ApiPath.teams, body),
    onSuccess: async (team) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.teams });
      setName("");
      onCreated(team);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    createTeam.mutate({ name: name.trim() });
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex items-end gap-3">
      <div className="flex-1">
        <TextField
          label="New team"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Platform"
          maxLength={200}
        />
      </div>
      <Button type="submit" disabled={createTeam.isPending || !name.trim()}>
        <Plus size={14} aria-hidden />
        {createTeam.isPending ? "Creating…" : "Create team"}
      </Button>
      {createTeam.isError && (
        <span className="pb-2 text-xs text-red-400">{errorMessage(createTeam.error)}</span>
      )}
    </form>
  );
}
