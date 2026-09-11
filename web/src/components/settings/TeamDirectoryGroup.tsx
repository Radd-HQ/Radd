import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderSync, Plus, TriangleAlert, X } from "lucide-react";
import { api } from "../../lib/api";
import { apiTeamDirectorySyncPath, apiTeamGroupPath, apiTeamGroupsPath } from "../../lib/constants";
import { queryKeys, teamGroupsPageQuery, teamGroupCandidatesPageQuery, teamGroupsPresenceQuery, TEAM_GROUPS_PAGE_SIZE } from "../../lib/queries";
import { usePermissions } from "../../lib/hooks";
import { useDirectory } from "../../lib/useDirectory";
import { pushToast, ToastKind } from "../../lib/toast";
import { Permission, type DirectorySyncResult, type Team, type TeamGroup } from "../../lib/types";
import { Button } from "../Button";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";
import { TextField } from "../TextField";
import { DirectoryPager } from "../DirectoryPager";
import { Modal } from "../Modal";

/** Groups remain directory-owned; a team attaches them and inherits their people. */
export function TeamGroupsSection({ team, canManage }: { team: Team; canManage: boolean }) {
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const canSync = permissions.global(Permission.teamUpdate);
  const [picking, setPicking] = useState(false);
  const held = useDirectory(team.id, TEAM_GROUPS_PAGE_SIZE, (q, page) => teamGroupsPageQuery(team.id, q, page));
  // Sync always reconciles ALL held groups, independently of the visible search.
  const presence = useQuery({ ...teamGroupsPresenceQuery(team.id), enabled: canSync });
  const lastPage = Math.max(0, Math.ceil(held.total / held.pageSize) - 1);
  if (held.isSuccess && held.page > lastPage) held.setPage(lastPage);
  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.teams }),
    queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(team.id) }),
  ]);
  const addGroup = useMutation({
    mutationFn: (groupId: string) => api.post<TeamGroup>(apiTeamGroupsPath(team.id), { group_id: groupId }),
    onSuccess: async () => { setPicking(false); await invalidate(); },
  });
  const removeGroup = useMutation({
    mutationFn: (groupId: string) => api.delete(apiTeamGroupPath(team.id, groupId)),
    onSuccess: invalidate,
  });
  const syncNow = useMutation({
    mutationFn: () => api.post<DirectorySyncResult>(apiTeamDirectorySyncPath(team.id), {}),
    onSuccess: async result => {
      pushToast(`${team.name}: +${result.added} / −${result.removed}`, ToastKind.success);
      await Promise.all([invalidate(), queryClient.invalidateQueries({ queryKey: ["groups"] })]);
    },
  });
  return <section aria-label={`${team.name} directory groups`} className="mb-4">
    <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">Directory groups</h4>
    <TextField type="search" label="Find attached groups" value={held.filter}
      onChange={event => held.setFilter(event.target.value)} placeholder="Search by name or directory path…" />
    <div aria-busy={held.busy} className="mt-2">
      {held.isPending ? <p className="text-xs text-fg-muted">Loading groups…</p>
        : held.isError ? <div className="space-y-2"><ErrorText error={held.error} />
          <Button variant="secondary" onClick={() => void held.refetch()}>Retry attached groups</Button></div>
        : !held.rows.length ? <p className="text-xs text-fg-muted">{held.q ? "No attached groups match your search." : "No groups attached."}</p>
        : <ul aria-label="Attached groups" className="max-h-[35dvh] space-y-1.5 overflow-y-auto">
          {held.rows.map(group => <li key={group.group_id} className="flex flex-wrap items-center gap-2 py-1 text-[13px]">
            <span className="min-w-0 break-words rounded border border-subtle bg-surface px-1.5 py-px text-[11px] text-fg-secondary" title={group.dn}>{group.name}</span>
            {group.directory_missing_since && <span className="flex items-center gap-1 text-[11px] text-status-warning-ink"
              title={`Missing since ${new Date(group.directory_missing_since).toLocaleString()} — renamed, moved, or deleted in AD. Its people are kept while it is missing.`}>
              <TriangleAlert size={12} aria-hidden />missing from AD
            </span>}
            {canManage && <IconButton danger onClick={() => removeGroup.mutate(group.group_id)} disabled={removeGroup.isPending}
              aria-label={`Remove ${group.name} from ${team.name}`}><X size={13} /></IconButton>}
          </li>)}
        </ul>}
    </div>
    <DirectoryPager {...held} onPage={held.setPage} label="attached groups" />
    <p className="my-2 text-xs text-fg-muted">Attached groups' people, including nested groups, count as team members.</p>
    <div className="flex flex-wrap items-center gap-2">
      {canSync && (presence.data?.total ?? 0) > 0 && <Button variant="ghost" onClick={() => syncNow.mutate()} disabled={syncNow.isPending}>
        <FolderSync size={13} aria-hidden />{syncNow.isPending ? "Syncing…" : "Sync all attached groups"}
      </Button>}
      {canSync && presence.isError && <div className="space-y-2"><ErrorText error={presence.error} />
        <Button variant="secondary" onClick={() => void presence.refetch()}>Retry sync availability</Button></div>}
      {canManage && <Button variant="ghost" onClick={() => { addGroup.reset(); setPicking(true); }}><Plus size={13} aria-hidden />Add a group</Button>}
    </div>
    {(removeGroup.isError || syncNow.isError || (!picking && addGroup.isError)) && <ErrorText className="mt-1" error={removeGroup.error ?? syncNow.error ?? addGroup.error} />}
    {picking && canManage && <GroupCandidates teamId={team.id} onClose={() => setPicking(false)} onSelect={id => addGroup.mutate(id)}
      pending={addGroup.isPending} error={addGroup.error} />}
  </section>;
}

function GroupCandidates({ teamId, onClose, onSelect, pending, error }: {
  teamId: string; onClose: () => void; onSelect: (id: string) => void; pending: boolean; error: Error | null;
}) {
  const groups = useDirectory(teamId, TEAM_GROUPS_PAGE_SIZE, (q, page) => teamGroupCandidatesPageQuery(teamId, q, page));
  return <Modal title="Add a group" onClose={onClose}>
    <TextField type="search" label="Find directory groups" value={groups.filter}
      onChange={event => groups.setFilter(event.target.value)} placeholder="Search by name or directory path…" />
    <div aria-busy={groups.busy} className="mt-2 max-h-[45dvh] overflow-y-auto">
      {groups.isPending ? <p className="text-xs text-fg-muted">Loading groups…</p>
        : groups.isError ? <div className="space-y-2"><ErrorText error={groups.error} />
          <Button variant="secondary" onClick={() => void groups.refetch()}>Retry group choices</Button></div>
        : !groups.rows.length ? <p className="py-3 text-sm text-fg-muted">{groups.q ? "No groups match your search." : "No more mirrored groups to add. New directory groups can be imported in Settings → Directory."}</p>
        : <ul aria-label="Group choices">{groups.rows.map(group => <li key={group.group_id}>
          <Button variant="ghost" className="h-auto min-h-11 w-full justify-start py-2 text-left" disabled={pending} onClick={() => onSelect(group.group_id)}>
            <span className="min-w-0">
              <span className="block break-words">{group.name}</span>
              <span className="block truncate text-xs text-fg-muted" title={group.dn}>{group.dn}</span>
              <span className="block text-xs text-fg-muted">{group.transitive_member_count} {group.transitive_member_count === 1 ? "person" : "people"} · {group.direct_member_count} direct{group.directory_missing_since ? " · missing from AD" : ""}</span>
            </span>
          </Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager {...groups} onPage={groups.setPage} label="group choices" />
    {error && <ErrorText error={error} className="mt-2" />}
  </Modal>;
}
