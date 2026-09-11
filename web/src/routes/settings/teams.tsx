import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Plus, UsersRound } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath, apiTeamPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { useDirectory } from "../../lib/useDirectory";
import { queryKeys, teamsPageQuery, teamByIdQuery, TEAMS_PAGE_SIZE } from "../../lib/queries";
import { Permission, type Team, type TeamCreate } from "../../lib/types";
import { Button } from "../../components/Button";
import { DirectoryPager } from "../../components/DirectoryPager";
import { EmptyState } from "../../components/EmptyState";
import { ErrorText } from "../../components/ErrorText";
import { Modal } from "../../components/Modal";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TeamPanel } from "../../components/settings/TeamPanel";
import { QueryError } from "../../components/QueryError";
import { formatDate } from "../../lib/dates";

export function TeamsSettingsPage() {
  const perms = usePermissions();
  const teams = useDirectory("teams", TEAMS_PAGE_SIZE, teamsPageQuery);
  const [selected, setSelected] = useState<Pick<Team, "id" | "name"> | null>(null);
  const lastPage = Math.max(0, Math.ceil(teams.total / teams.pageSize) - 1);
  if (teams.isSuccess && teams.page > lastPage) teams.setPage(lastPage);

  return <SettingsPage title="Teams"
    description="Group people, then attach a team to projects with a role — that's what grants project access. A team linked to an AD group takes its members from the directory.">
    <div className="mb-3"><TextField type="search" label="Find teams" placeholder="Search teams by name…"
      value={teams.filter} onChange={event => teams.setFilter(event.target.value)} /></div>
    <div aria-busy={teams.busy}>
      {teams.isPending ? <TableSkeleton rows={3} />
        : teams.isError ? <div className="space-y-2"><QueryError label="teams" error={teams.error} />
          <Button variant="secondary" onClick={() => void teams.refetch()}>Retry teams</Button></div>
        : !teams.rows.length ? <EmptyState icon={UsersRound} message={teams.filter ? "No teams match your search." : "No teams yet."} />
        : <ul aria-label="Teams" className="rounded-lg border border-subtle">
          {teams.rows.map(team => <li key={team.id} className="border-b border-subtle/60 last:border-b-0">
            <button type="button" onClick={() => setSelected(team)} aria-label={`Open ${team.name}`} aria-haspopup="dialog"
              className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-surface/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus cursor-pointer">
              <ChevronRight size={14} className="shrink-0 text-fg-muted" aria-hidden />
              <span className="min-w-0 break-words text-[13px] font-medium text-heading">{team.name}</span>
              <span className="ml-auto shrink-0 text-xs text-fg-faint">{formatDate(team.created_at)}</span>
            </button>
          </li>)}
        </ul>}
    </div>
    <DirectoryPager {...teams} onPage={teams.setPage} label="teams" />
    {perms.global(Permission.teamCreate) && <NewTeamForm onCreated={setSelected} />}
    {selected && <TeamDetails selected={selected} onClose={() => setSelected(null)} />}
  </SettingsPage>;
}

/** Direct detail keeps a new, renamed or off-page team reachable independently
 * of the current directory filter, without retaining every catalog row. */
function TeamDetails({ selected, onClose }: { selected: Pick<Team, "id" | "name">; onClose: () => void }) {
  const query = useQuery(teamByIdQuery(selected.id));
  return <Modal title={query.data?.name ?? selected.name} onClose={onClose} wide>
    {query.isPending ? <TableSkeleton rows={3} />
      : query.isError ? <div className="space-y-2"><QueryError label="team" error={query.error} />
        <Button variant="secondary" onClick={() => void query.refetch()}>Retry team</Button></div>
      : <>
        {query.data.can_manage && <RenameTeam key={query.data.id} team={query.data} />}
        <TeamPanel team={query.data} onDeleted={onClose} />
      </>}
  </Modal>;
}

function RenameTeam({ team }: { team: Team }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState({ base: team.name, name: team.name });
  useEffect(() => {
    setDraft(current => current.name === current.base ? { base: team.name, name: team.name } : current);
  }, [team.name]);
  const rename = useMutation({
    mutationFn: (name: string) => api.patch<Team>(apiTeamPath(team.id), { name }),
    onSuccess: async updated => {
      setDraft({ base: updated.name, name: updated.name });
      await queryClient.invalidateQueries({ queryKey: queryKeys.teams });
    },
  });
  return <form className="mb-4 flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); if (draft.name.trim()) rename.mutate(draft.name.trim()); }}>
    <div className="min-w-0 flex-1"><TextField label="Team name" value={draft.name} maxLength={200} disabled={rename.isPending}
      onChange={event => setDraft(current => ({ ...current, name: event.target.value }))} /></div>
    <Button type="submit" variant="secondary" disabled={rename.isPending || !draft.name.trim() || draft.name.trim() === team.name}>
      {rename.isPending ? "Saving…" : "Save name"}
    </Button>
    {rename.isError && <ErrorText error={rename.error} className="w-full" />}
  </form>;
}

function NewTeamForm({ onCreated }: { onCreated: (team: Team) => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const createTeam = useMutation({
    mutationFn: (body: TeamCreate) => api.post<Team>(ApiPath.teams, body),
    onSuccess: async team => {
      setName(""); onCreated(team);
      await queryClient.invalidateQueries({ queryKey: queryKeys.teams });
    },
  });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) createTeam.mutate({ name: name.trim() });
  };
  return <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-end gap-3">
    <div className="min-w-0 flex-1"><TextField label="New team" value={name} onChange={event => setName(event.target.value)} placeholder="Platform" maxLength={200} /></div>
    <Button type="submit" disabled={createTeam.isPending || !name.trim()}><Plus size={14} aria-hidden />{createTeam.isPending ? "Creating…" : "Create team"}</Button>
    {createTeam.isError && <ErrorText error={createTeam.error} className="w-full" />}
  </form>;
}
