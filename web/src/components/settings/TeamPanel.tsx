import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { api } from "../../lib/api";
import { apiTeamMemberPath, apiTeamMembersPath } from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { TeamAccessSection } from "./AccessInspector";
import { RoleGrantsSection } from "./RoleGrantsSection";
import {
  queryKeys,
  teamMembersQuery,
  usersQuery,
} from "../../lib/queries";
import {
  Permission,
  type Team,
  type TeamMember,
} from "../../lib/types";
import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { TeamGroupsSection } from "./TeamDirectoryGroup";
import { TeamStewardship } from "./TeamStewardship";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";

interface TeamPanelProps {
  team: Team;
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
 * A directory-linked team's roster is read-only — AD owns it (spec 87).
 */
export function TeamPanel({ team }: TeamPanelProps) {
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
  const members = useQuery(teamMembersQuery(team.id));
  // GET /users needs user.manage — only fetched when an affordance needs names.
  const users = useQuery({ ...usersQuery, enabled: canManageTeam, retry: false });

  const [userId, setUserId] = useState("");

  const memberIds = new Set((members.data ?? []).map((member) => member.user_id));
  const candidates = (users.data ?? []).filter((user) => user.active && !memberIds.has(user.id));
  const addMember = useMutation({
    mutationFn: (body: { user_id: string }) =>
      api.post<TeamMember>(apiTeamMembersPath(team.id), body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(team.id) });
      setUserId("");
    },
  });

  const removeMember = useMutation({
    mutationFn: (removeUserId: string) =>
      api.delete<void>(apiTeamMemberPath(team.id, removeUserId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(team.id) }),
  });




  const onAddMember = (event: FormEvent) => {
    event.preventDefault();
    if (userId) addMember.mutate({ user_id: userId });
  };

  return (
    <div className="border-t border-subtle/60 bg-surface/30 px-4 py-4">
      <TeamGroupsSection team={team} canManage={canManageTeam} />
      <TeamStewardship
        team={team}
        canAdminister={isOwner || perms.global(Permission.teamUpdate)}
      />
      <div className="grid gap-5 sm:grid-cols-2">
      <section aria-label={`${team.name} members`}>
        <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
          Members
        </h4>
        {members.isPending ? (
          <p className="text-xs text-fg-muted">Loading members…</p>
        ) : members.isError ? (
          <ErrorText error={members.error} />
        ) : (members.data ?? []).length === 0 ? (
          <p className="text-xs text-fg-muted">No members yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {(members.data ?? []).map((member) => (
              <li key={member.user_id} className="flex items-center gap-2 text-[13px]">
                <span className="text-fg">{member.name}</span>
                <span className="truncate text-xs text-fg-muted">{member.email}</span>
                {member.via_group && (
                  <span
                    className="rounded border border-sky-500/50 px-1 py-px text-[10px] text-sky-300"
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
        {canEditMembers && (
          <form onSubmit={onAddMember} className="mt-3 flex items-end gap-2">
            <div className="flex-1">
              <SelectField
                label="Add member"
                value={userId}
                onChange={(event) => setUserId(event.target.value)}
                hint={candidates.length === 0 ? "Everyone's already in this team" : undefined}
              >
                <option value="">Choose a user…</option>
                {candidates.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name}
                  </option>
                ))}
              </SelectField>
            </div>
            <Button type="submit" variant="ghost" disabled={!userId || addMember.isPending}>
              <Plus size={13} aria-hidden />
              Add
            </Button>
          </form>
        )}
        {addMember.isError && (
          <ErrorText className="mt-1" error={addMember.error} />
        )}
      </section>

      <RoleGrantsSection
        subject={{ teamId: team.id }}
        canManage={perms.global(Permission.roleUpdate)}
      />
      {/* RADD-809: the answer to "what does membership of this team confer" —
          admin-shaped (the endpoint is user.manage-gated), so only render the
          section for someone the server will answer. */}
      {perms.global(Permission.userManage) && <TeamAccessSection teamId={team.id} />}
      </div>
    </div>
  );
}
