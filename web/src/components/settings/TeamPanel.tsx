import { useState, type FormEvent } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, X } from "lucide-react";
import { api } from "../../lib/api";
import {
  apiProjectTeamPath,
  apiProjectTeamsPath,
  apiTeamMemberPath,
  apiTeamMembersPath,
} from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { TeamAccessSection } from "./AccessInspector";
import { RoleGrantsSection } from "./RoleGrantsSection";
import {
  projectTeamsQuery,
  projectsQuery,
  queryKeys,
  rolesQuery,
  teamMembersQuery,
  usersQuery,
} from "../../lib/queries";
import {
  Permission,
  type ProjectTeam,
  type ProjectTeamAttach,
  type Role,
  type Team,
  type TeamMember,
} from "../../lib/types";
import { Button } from "../Button";
import { Select } from "../Select";
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
  const projects = useQuery(projectsQuery());
  const roles = useQuery(rolesQuery());

  const [userId, setUserId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [roleId, setRoleId] = useState("");

  // A team's attachments live under each project — collect them across projects.
  const attachmentQueries = useQueries({
    queries: (projects.data ?? []).map((project) => projectTeamsQuery(project.id)),
  });
  const attachments = (projects.data ?? []).flatMap((project, index) =>
    (attachmentQueries[index]?.data ?? [])
      .filter((attachment: ProjectTeam) => attachment.team_id === team.id)
      .map((attachment: ProjectTeam) => ({ project, attachment })),
  );

  const memberIds = new Set((members.data ?? []).map((member) => member.user_id));
  const candidates = (users.data ?? []).filter((user) => user.active && !memberIds.has(user.id));
  const attachedProjectIds = new Set(attachments.map((entry) => entry.project.id));
  const attachableProjects = (projects.data ?? []).filter(
    (project) =>
      !attachedProjectIds.has(project.id) && perms.project(project, Permission.projectManage),
  );

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

  const invalidateProjectTeams = (targetProjectId: string) =>
    queryClient.invalidateQueries({ queryKey: queryKeys.projectTeams(targetProjectId) });

  const attach = useMutation({
    mutationFn: ({ targetProjectId, body }: { targetProjectId: string; body: ProjectTeamAttach }) =>
      api.post<ProjectTeam>(apiProjectTeamsPath(targetProjectId), body),
    onSuccess: async (_created, { targetProjectId }) => {
      await invalidateProjectTeams(targetProjectId);
      setProjectId("");
    },
  });

  const changeRole = useMutation({
    mutationFn: ({ targetProjectId, newRoleId }: { targetProjectId: string; newRoleId: string }) =>
      api.patch<ProjectTeam>(apiProjectTeamPath(targetProjectId, team.id), { role_id: newRoleId }),
    onSuccess: (_updated, { targetProjectId }) => invalidateProjectTeams(targetProjectId),
  });

  const detach = useMutation({
    mutationFn: (targetProjectId: string) =>
      api.delete<void>(apiProjectTeamPath(targetProjectId, team.id)),
    onSuccess: (_result, targetProjectId) => invalidateProjectTeams(targetProjectId),
  });

  const onAddMember = (event: FormEvent) => {
    event.preventDefault();
    if (userId) addMember.mutate({ user_id: userId });
  };

  const onAttach = (event: FormEvent) => {
    event.preventDefault();
    if (projectId && roleId) {
      attach.mutate({ targetProjectId: projectId, body: { team_id: team.id, role_id: roleId } });
    }
  };

  const roleList = roles.data ?? [];
  const roleName = (id: string) => roleList.find((role) => role.id === id)?.name ?? "?";
  const roleOptions = (list: Role[]) =>
    list.map((role) => (
      <option key={role.id} value={role.id}>
        {role.name}
      </option>
    ));

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

      <section aria-label={`${team.name} projects`}>
        <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
          Projects
        </h4>
        {attachments.length === 0 ? (
          <p className="text-xs text-fg-muted">Not attached to any project.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {attachments.map(({ project, attachment }) => (
              <li key={project.id} className="flex items-center gap-2 text-[13px]">
                <Link2 size={12} className="text-fg-faint" aria-hidden />
                <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg">
                  {project.key}
                </span>
                <span className="truncate text-fg">{project.name}</span>
                {perms.project(project, Permission.projectManage) ? (
                  <>
                    <Select
                      aria-label={`Role of ${team.name} in ${project.key}`}
                      value={attachment.role_id}
                      onChange={(newRoleId) =>
                        changeRole.mutate({
                          targetProjectId: project.id,
                          newRoleId,
                        })
                      }
                      size="sm"
                      className="ml-auto"
                      options={roleList.map((role) => ({ value: role.id, label: role.name }))}
                    />
                    <IconButton
                      danger
                      onClick={() => detach.mutate(project.id)}
                      disabled={detach.isPending}
                      aria-label={`Detach ${team.name} from ${project.key}`}
                    >
                      <X size={13} />
                    </IconButton>
                  </>
                ) : (
                  <span className="ml-auto rounded border border-strong px-1.5 py-px text-[11px] text-fg-secondary">
                    {roleName(attachment.role_id)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {attachableProjects.length > 0 && (
          <form onSubmit={onAttach} className="mt-3 flex items-end gap-2">
            <div className="flex-1">
              <SelectField
                label="Attach to project"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
              >
                <option value="">Choose a project…</option>
                {attachableProjects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.key} — {project.name}
                  </option>
                ))}
              </SelectField>
            </div>
            <SelectField
              label="Role"
              value={roleId}
              onChange={(event) => setRoleId(event.target.value)}
            >
              <option value="">Choose a role…</option>
              {roleOptions(roleList)}
            </SelectField>
            <Button type="submit" variant="ghost" disabled={!projectId || !roleId || attach.isPending}>
              <Plus size={13} aria-hidden />
              Attach
            </Button>
          </form>
        )}
        {(attach.isError || changeRole.isError || detach.isError) && (
          <ErrorText className="mt-1" error={attach.error ?? changeRole.error ?? detach.error} />
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
