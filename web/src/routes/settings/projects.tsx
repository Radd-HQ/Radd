import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, UserRound } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import {
  groupsQuery,
  queryKeys,
  roleGrantsQuery,
  rolesQuery,
  teamsQuery,
  usersQuery,
} from "../../lib/queries";
import {
  GrantSubject,
  Permission,
  type Project,
  type Role,
  type RoleGrant,
  type RoleGrantCreate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { ErrorText } from "../../components/ErrorText";
import { IconButton } from "../../components/IconButton";
import { QueryError } from "../../components/QueryError";
import { Select } from "../../components/Select";
import { TableSkeleton } from "../../components/TableSkeleton";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { SUBJECT_ICON, SubjectPicker, type Subject } from "../../components/settings/SubjectPicker";
import { X } from "lucide-react";
import { projectsQuery } from "../../lib/queries";

/**
 * Project access (spec 09/50; one model since RADD-929).
 *
 * This page used to be two lists — "Direct members" (`project_members`) and
 * "Team attachments" (`project_teams`) — beside a third way to say the same
 * thing on the Teams page. All three resolved into one union in
 * `authz._granted_role_ids`, so which list a person's access appeared in was a
 * fact about which button an admin had clicked, not about what they could do.
 *
 * Now: one list of role grants scoped to this project, over the same three
 * subject kinds the grant table has always supported — user, team, and
 * directory GROUP, the last of which had no UI at all before.
 *
 * Instance-wide grants are deliberately absent. This answers "who was given
 * access to THIS project"; folding in everyone with a global role would make
 * revoking look possible here where it is not.
 */
export function ProjectsSettingsPage({ projectId }: { projectId?: string }) {
  const projects = useQuery(projectsQuery());
  const roles = useQuery(rolesQuery());
  const project = (projects.data ?? []).find((entry) => entry.id === projectId);

  return (
    <SettingsPage
      title="Project access"
      description="Who can do what here. Each row grants one role to one person, team, or directory group — a grant to a team or group reaches everyone in it, nesting included."
    >
      {projects.isPending || roles.isPending ? (
        <TableSkeleton rows={3} />
      ) : projects.isError ? (
        <QueryError label="projects" error={projects.error} />
      ) : !project ? (
        <p className="text-sm text-fg-muted">Project not found.</p>
      ) : (
        <ProjectGrants key={project.id} project={project} roles={roles.data ?? []} />
      )}
    </SettingsPage>
  );
}

function ProjectGrants({ project, roles }: { project: Project; roles: Role[] }) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  // RADD-826: entitling your own project is delegated — member.create here,
  // which project.manage implies. It does NOT need global role.update, and the
  // server enforces exactly this split on the same endpoints.
  const canGrant = perms.project(project, Permission.memberCreate);
  const canRevoke = perms.project(project, Permission.memberDelete);

  const grants = useQuery(roleGrantsQuery({ projectId: project.id }));
  const users = useQuery({ ...usersQuery, enabled: canGrant, retry: false });
  const teams = useQuery({ ...teamsQuery(), enabled: canGrant });
  const groups = useQuery({ ...groupsQuery(), enabled: canGrant });

  const [subject, setSubject] = useState<Subject | null>(null);
  const [roleId, setRoleId] = useState("");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.roleGrants });

  const grant = useMutation({
    mutationFn: () => {
      const body: RoleGrantCreate = {
        role_id: roleId,
        project_ids: [project.id],
        space_ids: [],
        ...(subject?.type === GrantSubject.team
          ? { team_id: subject.id }
          : subject?.type === GrantSubject.group
            ? { group_id: subject.id }
            : { user_id: subject?.id }),
      };
      return api.post(ApiPath.roleGrants, body);
    },
    onSuccess: async () => {
      await invalidate();
      setSubject(null);
      setRoleId("");
    },
  });

  const revoke = useMutation({
    mutationFn: (grantId: string) => api.delete(`${ApiPath.roleGrants}/${grantId}`),
    onSuccess: invalidate,
  });

  // One flat candidate list — the picker filters by name across kinds, so an
  // admin types "render" and gets the person, the team and the AD group without
  // first deciding which of the three they meant.
  const candidates: Subject[] = [
    ...(teams.data ?? []).map((team) => ({
      type: GrantSubject.team,
      id: team.id,
      name: team.name,
    })),
    ...(groups.data ?? []).map((group) => ({
      type: GrantSubject.group,
      id: group.id,
      name: group.name,
    })),
    ...(users.data ?? [])
      .filter((user) => user.active)
      .map((user) => ({ type: GrantSubject.user, id: user.id, name: user.name })),
  ];
  const nameOf = new Map(candidates.map((entry) => [entry.id, entry.name]));
  const roleName = (id: string) => roles.find((role) => role.id === id)?.name ?? "?";

  const subjectOf = (row: RoleGrant): { type: Subject["type"]; id: string } =>
    row.team_id
      ? { type: GrantSubject.team, id: row.team_id }
      : row.group_id
        ? { type: GrantSubject.group, id: row.group_id }
        : { type: GrantSubject.user, id: row.user_id ?? "" };

  const all = grants.data ?? [];
  const search = useListFilter(all, (row) => [
    nameOf.get(subjectOf(row).id) ?? "",
    roleName(row.role_id),
  ]);
  const list = search.filtered;

  return (
    <div className="flex flex-col gap-4">
      {grants.isPending ? (
        <TableSkeleton rows={3} />
      ) : grants.isError ? (
        <QueryError label="project access" error={grants.error} />
      ) : all.length === 0 ? (
        <EmptyState icon={UserRound} message="Nobody has been granted access to this project yet." />
      ) : (
        <>
          {/* A real project reaches three digits of grants — this one has 31 on
              the dev dataset, which already pushes the grant form below the
              fold. Same threshold and control as every other settings list. */}
          {all.length > 8 && (
            <ListSearchInput
              value={search.filter}
              onChange={search.setFilter}
              placeholder="Filter by name or role…"
              total={all.length}
              matched={list.length}
              noun="grants"
            />
          )}
          {list.length === 0 ? (
            <EmptyState icon={UserRound} message={`Nothing matches “${search.filter.trim()}”.`} />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((row) => {
                const who = subjectOf(row);
                const Icon = SUBJECT_ICON[who.type];
                return (
                  <li
                    key={row.id}
                    className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0"
                  >
                    <Icon size={13} className="shrink-0 text-fg-faint" aria-hidden />
                    <span className="truncate text-[13px] text-fg">
                      {nameOf.get(who.id) ?? who.id}
                    </span>
                    {/* Only the kinds that reach OTHER people are labelled. A
                        "USER" chip on every row of a mostly-user list is noise
                        the icon already carries; "TEAM" and "GROUP" say the
                        thing that actually changes how you read the row. */}
                    {who.type !== GrantSubject.user && (
                      <span className="rounded border border-strong px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-muted">
                        {who.type}
                      </span>
                    )}
                    <span className="ml-auto rounded border border-strong px-1.5 py-px text-[11px] text-fg-secondary">
                      {roleName(row.role_id)}
                    </span>
                    {canRevoke && (
                      <IconButton
                        danger
                        onClick={() => revoke.mutate(row.id)}
                        disabled={revoke.isPending}
                        aria-label={`Revoke ${roleName(row.role_id)} from ${nameOf.get(who.id) ?? who.id}`}
                      >
                        <X size={13} />
                      </IconButton>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      {revoke.isError && <ErrorText error={revoke.error} />}

      {canGrant && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (subject && roleId) grant.mutate();
          }}
        >
          <div className="min-w-64 flex-1">
            <p className="mb-1.5 text-xs font-medium text-fg-secondary">Person, team or group</p>
            <SubjectPicker
              subjects={candidates}
              value={subject}
              onChange={setSubject}
              placeholder="Search people, teams and directory groups…"
            />
          </div>
          <div className="min-w-44">
            <p className="mb-1.5 text-xs font-medium text-fg-secondary">Role</p>
            <Select
              aria-label="Role to grant"
              value={roleId}
              onChange={setRoleId}
              options={[
                { value: "", label: "Choose a role…" },
                ...roles.map((role) => ({ value: role.id, label: role.name })),
              ]}
            />
          </div>
          <Button type="submit" disabled={!subject || !roleId || grant.isPending}>
            <Plus size={14} aria-hidden />
            {grant.isPending ? "Granting…" : "Grant access"}
          </Button>
          {grant.isError && <ErrorText className="w-full" error={grant.error} />}
        </form>
      )}

      <p className="flex items-start gap-1.5 text-[11px] text-fg-faint">
        <Globe size={12} className="mt-0.5 shrink-0" aria-hidden />
        <span>
          People with an instance-wide role hold it here too and are not listed — those
          grants are managed on Settings → Roles, not per project.
        </span>
      </p>
    </div>
  );
}
