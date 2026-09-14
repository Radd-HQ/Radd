import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { api } from "../../lib/api";
import { apiTeamMemberPath, apiTeamMembersPath } from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { TeamAccessSection } from "./AccessInspector";
import { RoleGrantsSection } from "./RoleGrantsSection";
import {
  queryKeys,
  teamMembersPageQuery,
  TEAM_MEMBERS_PAGE_SIZE,
  type PeopleChoice,
} from "../../lib/queries";
import {
  Permission,
  type Team,
  type TeamMember,
} from "../../lib/types";
import { Button } from "../Button";
import { PeopleDirectorySelect } from "../PeopleDirectorySelect";
import { DirectoryPager } from "../DirectoryPager";
import { TextField } from "../TextField";
import { useDirectory } from "../../lib/useDirectory";
import { TeamGroupsSection } from "./TeamDirectoryGroup";
import { TeamStewardship } from "./TeamStewardship";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";
import { ChangeHistoryPanel } from "../history/ChangeHistoryPanel";

interface TeamPanelProps {
  team: Team;
  onDeleted?: () => void;
}

/**
 * Expanded team row: membership + project attachments with data-driven roles.
 *
 * Two gates, deliberately separate (spec 87). `team.can_manage` is resolved
 * server-side and covers owners, managers and global-atom holders — it decides
 * who edits the roster. Attaching the team to a project needs project.manage
 * THERE (spec 06/09): a team leader decides who is on their team, never what
 * their team is entitled to.
 *
 * Group-derived people are read-only; direct membership remains editable.
 */
export function TeamPanel({ team, onDeleted }: TeamPanelProps) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const me = useCurrentUser();
  const canManageTeam = team.can_manage;
  // RADD-829: no team is directory-owned any more — membership is always
  // hand-editable; the directory arrives as GROUP members instead.
  const canEditMembers = canManageTeam;
  // Appointing managers / transferring is the owner's call (or an atom holder's);
  // a delegate must not be able to appoint further delegates.
  const isOwner = Boolean(me && team.owner_id === me.id);
  const members = useDirectory(team.id, TEAM_MEMBERS_PAGE_SIZE,
    (q, page) => teamMembersPageQuery(team.id, q, page));
  const lastPage = Math.max(0, Math.ceil(members.total / members.pageSize) - 1);
  if (members.isSuccess && members.page > lastPage) members.setPage(lastPage);
  const [candidate, setCandidate] = useState<PeopleChoice | null>(null);

  const addMember = useMutation({
    mutationFn: (body: { user_id: string }) =>
      api.post<TeamMember>(apiTeamMembersPath(team.id), body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(team.id) });
      setCandidate(null);
    },
  });

  const removeMember = useMutation({
    mutationFn: (removeUserId: string) =>
      api.delete<void>(apiTeamMemberPath(team.id, removeUserId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(team.id) }),
  });


  const onAddMember = (event: FormEvent) => {
    event.preventDefault();
    if (candidate) addMember.mutate({ user_id: candidate.id });
  };

  return (
    <div className="border-t border-subtle/60 bg-surface/30 px-4 py-4">
      <TeamGroupsSection team={team} canManage={canManageTeam} />
      <TeamStewardship
        team={team}
        onDeleted={onDeleted}
        canAdminister={isOwner || perms.global(Permission.teamUpdate)}
      />
      <div className="grid gap-5 sm:grid-cols-2">
      <section aria-label={`${team.name} members`}>
        <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
          Members
        </h4>
        <TextField label="Find members" type="search" value={members.filter}
          onChange={event => members.setFilter(event.target.value)} placeholder="Search by name or email…" />
        <div aria-busy={members.busy} className="mt-2">
        {members.isPending ? (
          <p className="text-xs text-fg-muted">Loading members…</p>
        ) : members.isError ? (
          <div className="space-y-2"><ErrorText error={members.error} /><Button variant="secondary" onClick={() => void members.refetch()}>Retry members</Button></div>
        ) : members.rows.length === 0 ? (
          <p className="text-xs text-fg-muted">{members.q ? "No members match your search." : "No members yet."}</p>
        ) : (
          <ul aria-label="Team members" className="flex max-h-[45dvh] flex-col gap-1 overflow-y-auto">
            {members.rows.map((member) => (
              <li key={member.user_id} className="flex flex-wrap items-center gap-2 py-1 text-[13px]">
                <span className="min-w-0 break-words text-fg">{member.name}</span>
                <span className="truncate text-xs text-fg-muted">{member.email}</span>
                {member.via_group && (
                  <span
                    className="rounded border border-subtle bg-surface px-1 py-px text-[10px] text-fg-muted"
                    title={`Member via the ${member.via_group} group — managed by the directory sync.`}
                  >
                    {member.via_group}
                  </span>
                )}
                {canEditMembers && !member.via_group && (
                  <IconButton
                    danger
                    onClick={() => removeMember.mutate(member.user_id)}
                    disabled={removeMember.isPending}
                    aria-label={`Remove ${member.name} from ${team.name}`}
                    className="ml-auto"
                  >
                    <X size={13} />
                  </IconButton>
                )}
              </li>
            ))}
          </ul>
        )}
        </div>
        <DirectoryPager {...members} onPage={members.setPage} label="members" />
        {removeMember.isError && <ErrorText className="mt-1" error={removeMember.error} />}
        {canEditMembers && (
          <form onSubmit={onAddMember} className="mt-3 flex items-end gap-2">
            <div className="flex-1">
              <PeopleDirectorySelect kind="person" candidateTeamId={team.id}
                label="Add member" emptyLabel="Choose a person…" value={candidate} onChange={setCandidate} />
            </div>
            <Button type="submit" variant="ghost" disabled={!candidate || addMember.isPending}>
              <Plus size={13} aria-hidden />
              Add
            </Button>
          </form>
        )}
        {addMember.isError && (
          <ErrorText className="mt-1" error={addMember.error} />
        )}
      </section>

      {perms.anyProject(Permission.itemRead) && <RoleGrantsSection
        subject={{ teamId: team.id }}
        canManage={perms.global(Permission.roleUpdate)}
      />}
      {/* RADD-809: the answer to "what does membership of this team confer" —
          admin-shaped (the endpoint is user.manage-gated), so only render the
          section for someone the server will answer. */}
      {perms.global(Permission.userManage) && <TeamAccessSection teamId={team.id} />}
      <ChangeHistoryPanel entityType="team" entityId={team.id} />
      </div>
    </div>
  );
}
