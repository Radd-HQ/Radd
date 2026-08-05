import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Lock, Plus, UserRound, X } from "lucide-react";
import { ApiError, api } from "../../lib/api";
import {
  apiProjectMemberPath,
  apiProjectMembersPath,
  apiProjectTeamPath,
  apiProjectTeamsPath,
} from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import {
  projectMembersQuery,
  projectTeamsQuery,
  projectsQuery,
  queryKeys,
  rolesQuery,
  teamsQuery,
  usersQuery,
} from "../../lib/queries";
import {
  Permission,
  type Project,
  type ProjectMember,
  type ProjectMemberUpsert,
  type ProjectTeam,
  type ProjectTeamAttach,
  type Role,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Select } from "../../components/Select";
import { SelectField } from "../../components/SelectField";
import { TableSkeleton } from "../../components/TableSkeleton";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { IconButton } from "../../components/IconButton";
import { ErrorText } from "../../components/ErrorText";

/**
 * Project access admin (spec 09/50): direct user memberships and team
 * attachments for one project, each carrying a data-driven role (spec 06). The
 * project comes from the URL context (`projectId`), not an in-page picker.
 */
export function ProjectsSettingsPage({ projectId }: { projectId?: string }) {
  const projects = useQuery(projectsQuery());
  const roles = useQuery(rolesQuery());

  const project = (projects.data ?? []).find((entry) => entry.id === projectId);

  return (
    <SettingsPage
      title="Project access"
      description="Who can do what in this project: direct members and attached teams, each with a role."
    >
      {projects.isPending || roles.isPending ? (
        <TableSkeleton rows={3} />
      ) : projects.isError ? (
        <QueryError label="projects" error={projects.error} />
      ) : !project ? (
        <p className="text-sm text-fg-muted">Project not found.</p>
      ) : (
        <div className="flex flex-col gap-8">
          <MembersSection key={`m-${project.id}`} project={project} roles={roles.data ?? []} />
          <TeamsSection key={`t-${project.id}`} project={project} roles={roles.data ?? []} />
        </div>
      )}
    </SettingsPage>
  );
}

function roleName(roles: Role[], roleId: string): string {
  return roles.find((role) => role.id === roleId)?.name ?? "?";
}

const roleOptions = (roles: Role[]) => roles.map((role) => ({ value: role.id, label: role.name }));

const roleOptionElements = (roles: Role[]) =>
  roles.map((role) => (
    <option key={role.id} value={role.id}>
      {role.name}
    </option>
  ));

function MembersSection({ project, roles }: { project: Project; roles: Role[] }) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const canManage = perms.project(project, Permission.projectManage);
  const members = useQuery({ ...projectMembersQuery(project.id), enabled: canManage });
  const users = useQuery({ ...usersQuery, enabled: canManage, retry: false });
  const [userId, setUserId] = useState("");
  const [roleId, setRoleId] = useState("");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.projectMembers(project.id) });

  const upsert = useMutation({
    mutationFn: (body: ProjectMemberUpsert) =>
      api.post<ProjectMember>(apiProjectMembersPath(project.id), body),
    onSuccess: async () => {
      await invalidate();
      setUserId("");
    },
  });
  const changeRole = useMutation({
    mutationFn: ({ memberId, newRoleId }: { memberId: string; newRoleId: string }) =>
      api.patch<ProjectMember>(apiProjectMemberPath(project.id, memberId), { role_id: newRoleId }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (memberId: string) => api.delete<void>(apiProjectMemberPath(project.id, memberId)),
    onSuccess: invalidate,
  });

  const usersById = new Map((users.data ?? []).map((user) => [user.id, user]));
  const memberIds = new Set((members.data ?? []).map((member) => member.user_id));
  const candidates = (users.data ?? []).filter((user) => user.active && !memberIds.has(user.id));
  const forbidden = members.error instanceof ApiError && members.error.status === 403;

  const onAdd = (event: FormEvent) => {
    event.preventDefault();
    if (userId && roleId) upsert.mutate({ user_id: userId, role_id: roleId });
  };

  return (
    <section aria-label={`${project.key} members`}>
      <h3 className="mb-2 text-sm font-semibold text-fg">Direct members</h3>
      {!canManage || forbidden ? (
        <EmptyState icon={Lock} message="Managing project members requires project.manage." />
      ) : members.isPending ? (
        <TableSkeleton rows={2} />
      ) : members.isError ? (
        <ErrorText size="sm" error={members.error} />
      ) : (members.data ?? []).length === 0 ? (
        <EmptyState icon={UserRound} message="No direct members — access may come via teams." />
      ) : (
        <ul className="rounded-lg border border-subtle">
          {(members.data ?? []).map((member) => {
            const user = usersById.get(member.user_id);
            return (
              <li
                key={member.user_id}
                className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 text-[13px] last:border-b-0"
              >
                <span className="text-heading">{user?.name ?? member.user_id}</span>
                <Select
                  aria-label={`Role of ${user?.name ?? member.user_id}`}
                  value={member.role_id}
                  onChange={(newRoleId) => changeRole.mutate({ memberId: member.user_id, newRoleId })}
                  size="sm"
                  className="ml-auto"
                  options={roleOptions(roles)}
                />
                <IconButton
                  danger
                  onClick={() => remove.mutate(member.user_id)}
                  disabled={remove.isPending}
                  aria-label={`Remove ${user?.name ?? member.user_id} from ${project.key}`}
                >
                  <X size={13} />
                </IconButton>
              </li>
            );
          })}
        </ul>
      )}
      {canManage && !forbidden && (
        <form onSubmit={onAdd} className="mt-3 flex items-end gap-2">
          <div className="flex-1">
            <SelectField
              label="Add member"
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              hint={candidates.length === 0 ? "Every user is already a direct member" : undefined}
            >
              <option value="">Choose a user…</option>
              {candidates.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name}
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
            {roleOptionElements(roles)}
          </SelectField>
          <Button type="submit" disabled={!userId || !roleId || upsert.isPending}>
            <Plus size={14} aria-hidden />
            {upsert.isPending ? "Adding…" : "Add member"}
          </Button>
        </form>
      )}
      {(upsert.isError || changeRole.isError) && (
        <ErrorText className="mt-1" error={upsert.error ?? changeRole.error} />
      )}
    </section>
  );
}

function TeamsSection({ project, roles }: { project: Project; roles: Role[] }) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const canManage = perms.project(project, Permission.projectManage);
  const attachments = useQuery(projectTeamsQuery(project.id));
  const teams = useQuery(teamsQuery());
  const [teamId, setTeamId] = useState("");
  const [roleId, setRoleId] = useState("");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.projectTeams(project.id) });

  const attach = useMutation({
    mutationFn: (body: ProjectTeamAttach) =>
      api.post<ProjectTeam>(apiProjectTeamsPath(project.id), body),
    onSuccess: async () => {
      await invalidate();
      setTeamId("");
    },
  });
  const changeRole = useMutation({
    mutationFn: ({ targetTeamId, newRoleId }: { targetTeamId: string; newRoleId: string }) =>
      api.patch<ProjectTeam>(apiProjectTeamPath(project.id, targetTeamId), { role_id: newRoleId }),
    onSuccess: invalidate,
  });
  const detach = useMutation({
    mutationFn: (targetTeamId: string) =>
      api.delete<void>(apiProjectTeamPath(project.id, targetTeamId)),
    onSuccess: invalidate,
  });

  const teamsById = new Map((teams.data ?? []).map((team) => [team.id, team]));
  const attachedIds = new Set((attachments.data ?? []).map((entry) => entry.team_id));
  const attachable = (teams.data ?? []).filter((team) => !attachedIds.has(team.id));

  const onAttach = (event: FormEvent) => {
    event.preventDefault();
    if (teamId && roleId) attach.mutate({ team_id: teamId, role_id: roleId });
  };

  return (
    <section aria-label={`${project.key} teams`}>
      <h3 className="mb-2 text-sm font-semibold text-fg">Team attachments</h3>
      {attachments.isPending ? (
        <TableSkeleton rows={2} />
      ) : attachments.isError ? (
        <ErrorText size="sm" error={attachments.error} />
      ) : (attachments.data ?? []).length === 0 ? (
        <EmptyState icon={Link2} message="No teams attached." />
      ) : (
        <ul className="rounded-lg border border-subtle">
          {(attachments.data ?? []).map((entry) => {
            const team = teamsById.get(entry.team_id);
            return (
              <li
                key={entry.team_id}
                className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 text-[13px] last:border-b-0"
              >
                <Link2 size={12} className="text-fg-faint" aria-hidden />
                <span className="text-heading">{team?.name ?? entry.team_id}</span>
                {canManage ? (
                  <>
                    <Select
                      aria-label={`Role of team ${team?.name ?? entry.team_id}`}
                      value={entry.role_id}
                      onChange={(newRoleId) =>
                        changeRole.mutate({
                          targetTeamId: entry.team_id,
                          newRoleId,
                        })
                      }
                      size="sm"
                      className="ml-auto"
                      options={roleOptions(roles)}
                    />
                    <IconButton
                      danger
                      onClick={() => detach.mutate(entry.team_id)}
                      disabled={detach.isPending}
                      aria-label={`Detach ${team?.name ?? entry.team_id} from ${project.key}`}
                    >
                      <X size={13} />
                    </IconButton>
                  </>
                ) : (
                  <span className="ml-auto rounded border border-strong px-1.5 py-px text-[11px] text-fg-secondary">
                    {roleName(roles, entry.role_id)}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {canManage && (
        <form onSubmit={onAttach} className="mt-3 flex items-end gap-2">
          <div className="flex-1">
            <SelectField
              label="Attach team"
              value={teamId}
              onChange={(event) => setTeamId(event.target.value)}
              hint={attachable.length === 0 ? "Every team is already attached" : undefined}
            >
              <option value="">Choose a team…</option>
              {attachable.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
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
            {roleOptionElements(roles)}
          </SelectField>
          <Button type="submit" disabled={!teamId || !roleId || attach.isPending}>
            <Plus size={14} aria-hidden />
            {attach.isPending ? "Attaching…" : "Attach"}
          </Button>
        </form>
      )}
      {(attach.isError || changeRole.isError || detach.isError) && (
        <ErrorText className="mt-1" error={attach.error ?? changeRole.error ?? detach.error} />
      )}
    </section>
  );
}
