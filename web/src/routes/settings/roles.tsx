import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Plus, ShieldCheck } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiRolePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { permissionsCatalogQuery, queryKeys, rolesQuery } from "../../lib/queries";
import {
  BASELINE_ROLE_KEY,
  type BaselinePreflight,
  Permission,
  type PermissionInfo,
  type PermissionValue,
  type Role,
  type RoleUpdate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { PermissionMatrix } from "../../components/settings/PermissionMatrix";
import { RoleGlobalGrants } from "../../components/settings/RoleGlobalGrants";
import { RoleModal } from "../../components/settings/RoleModal";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";

/** Roles admin (spec 09): list + expandable permission matrix per role. */
export function RolesSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.roleUpdate);
  const roles = useQuery(rolesQuery());
  const catalog = useQuery(permissionsCatalogQuery);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const list = roles.data ?? [];

  return (
    <SettingsPage
      title="Roles"
      description="Named permission sets granted to project members and team attachments. Builtin roles are immutable — except Baseline, which is what everyone holds before any role is granted."
      actions={
        canManage && (
          <Button onClick={() => setCreating(true)}>
            <Plus size={14} aria-hidden />
            New role
          </Button>
        )
      }
    >
      {roles.isPending || catalog.isPending ? (
        <TableSkeleton rows={4} />
      ) : roles.isError || catalog.isError ? (
        <QueryError label="roles" error={roles.error ?? catalog.error} />
      ) : list.length === 0 ? (
        <EmptyState icon={ShieldCheck} message="No roles yet." />
      ) : (
        <ul className="rounded-lg border border-subtle">
          {list.map((role) => {
            const expanded = expandedId === role.id;
            return (
              <li key={role.id} className="border-b border-subtle/60 last:border-b-0">
                <button
                  type="button"
                  onClick={() => setExpandedId(expanded ? null : role.id)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-surface/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus cursor-pointer"
                >
                  {expanded ? (
                    <ChevronDown size={14} className="text-fg-muted" aria-hidden />
                  ) : (
                    <ChevronRight size={14} className="text-fg-muted" aria-hidden />
                  )}
                  <span className="text-[13px] font-medium text-heading">{role.name}</span>
                  <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
                    {role.key}
                  </span>
                  {role.key === BASELINE_ROLE_KEY ? (
                    <span
                      className="rounded border border-accent/50 bg-accent/10 px-1.5 py-px text-[11px] text-accent-text"
                      title="Held by every active user, on every project, without being granted"
                    >
                      Everyone, always
                    </span>
                  ) : (
                    role.is_builtin && (
                      <span className="rounded border border-accent/50 px-1.5 py-px text-[11px] text-accent-text">
                        Builtin
                      </span>
                    )
                  )}
                  <span className="ml-auto text-xs text-fg-faint">
                    {role.permissions.length}{" "}
                    {role.permissions.length === 1 ? "permission" : "permissions"}
                  </span>
                </button>
                {expanded && (
                  <RolePanel
                    role={role}
                    catalog={catalog.data ?? []}
                    canManage={canManage}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
      {creating && (
        <RoleModal
          catalog={catalog.data ?? []}
          onClose={() => setCreating(false)}
          onCreated={(role) => setExpandedId(role.id)}
        />
      )}
    </SettingsPage>
  );
}

interface RolePanelProps {
  role: Role;
  catalog: PermissionInfo[];
  canManage: boolean;
}

/** RADD-836 U4: the blast radius, shown BEFORE the save — a permission
 * system that cannot say what a change will do gets changed by trial and
 * error on production. */
function RoleImpact({ roleId, dirty }: { roleId: string; dirty: boolean }) {
  const impact = useQuery({
    queryKey: ["role-impact", roleId] as const,
    queryFn: () =>
      api.get<{ role_id: string; total_users: number; everyone: boolean }>(
        `${apiRolePath(roleId)}/impact`,
      ),
    enabled: dirty,
    staleTime: 60_000,
  });
  if (!dirty || !impact.data) return null;
  return (
    <span
      className={
        "text-xs " + (impact.data.everyone ? "font-medium text-amber-400" : "text-fg-muted")
      }
    >
      {impact.data.everyone
        ? `Affects EVERY active user (${impact.data.total_users})`
        : `Affects ${impact.data.total_users} ${impact.data.total_users === 1 ? "person" : "people"}`}
    </span>
  );
}


/** RADD-825: the Baseline pre-flight — "storing THIS set removes access for
 * N users across M projects, here is who and where", computed server-side
 * through the real resolvers against the EDITED (unsaved) permission set. An
 * admin grants the roles that restore intended access and re-runs it until
 * the diff is what they meant. */
function BaselinePreflight({ selected }: { selected: PermissionValue[] }) {
  const run = useMutation({
    mutationFn: () =>
      api.post<BaselinePreflight>(`${ApiPath.roles}/baseline/preflight`, {
        permissions: selected,
      }),
  });
  const report = run.data;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3">
      <div className="flex items-center gap-3">
        <Button variant="secondary" size="sm" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Checking every account…" : "Pre-flight this change"}
        </Button>
        <span className="text-xs text-fg-muted">
          Who would lose access if this set were saved — checked against every active account
          before anything changes.
        </span>
      </div>
      {run.isError && <p className="text-xs text-red-400">{errorMessage(run.error)}</p>}
      {report && (
        <div className="flex flex-col gap-2 text-xs">
          <p
            className={
              report.users_affected > 0 ? "font-medium text-amber-400" : "font-medium text-fg-secondary"
            }
          >
            {report.users_affected === 0
              ? `No one loses anything (${report.total_users_checked} accounts checked).`
              : `${report.users_affected} of ${report.total_users_checked} accounts lose access` +
                (report.projects_affected > 0
                  ? `, across ${report.projects_affected} ${report.projects_affected === 1 ? "project" : "projects"}.`
                  : ".")}
          </p>
          {(report.narrowed.length > 0 || report.removed.length > 0) && (
            <p className="text-fg-muted">
              {report.narrowed.length > 0 && (
                <>Narrows: {report.narrowed.join(", ")} (kept in a tighter form). </>
              )}
              {report.removed.length > 0 && <>Removes: {report.removed.join(", ")}.</>}
            </p>
          )}
          {report.rows.length > 0 && (
            <div className="max-h-64 overflow-y-auto rounded-md border border-subtle">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-subtle text-fg-muted">
                    <th className="px-2 py-1 font-medium">Person</th>
                    <th className="px-2 py-1 font-medium">Loses</th>
                    <th className="px-2 py-1 font-medium">Still reads</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((row) => (
                    <tr key={row.user_id} className="border-b border-subtle/60 align-top">
                      <td className="px-2 py-1 whitespace-nowrap">{row.name}</td>
                      <td className="px-2 py-1 text-fg-secondary">{row.lost.join(", ")}</td>
                      <td className="px-2 py-1 text-fg-muted">
                        {row.retained_project_keys.length > 0
                          ? row.retained_project_keys.join(", ")
                          : row.lost_project_count > 0
                            ? "nothing"
                            : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {report.truncated && (
            <p className="text-fg-faint">
              Showing the first {report.rows.length} of {report.users_affected} affected accounts —
              the counts above cover everyone.
            </p>
          )}
        </div>
      )}
    </div>
  );
}


/** Expanded role row: matrix (editable on custom roles), save + delete. */
function RolePanel({ role, catalog, canManage }: RolePanelProps) {
  const queryClient = useQueryClient();
  // Baseline is builtin AND editable — the one exception, and the point of
  // RADD-773: it is what every active user holds without being granted
  // anything, so an admin has to be able to change it. Name/description stay
  // fixed (it is a builtin); the permission matrix does not.
  const isBaseline = role.key === BASELINE_ROLE_KEY;
  const editable = canManage && !role.is_builtin;
  const permissionsEditable = canManage && (editable || isBaseline);
  const [name, setName] = useState(role.name);
  const [description, setDescription] = useState(role.description);
  const [selected, setSelected] = useState<PermissionValue[]>(role.permissions);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const save = useMutation({
    mutationFn: (body: RoleUpdate) => api.patch<Role>(apiRolePath(role.id), body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.roles }),
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiRolePath(role.id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.roles }),
  });

  const dirty =
    name !== role.name ||
    description !== role.description ||
    selected.length !== role.permissions.length ||
    selected.some((permission) => !role.permissions.includes(permission));

  const toggle = (permission: PermissionValue) =>
    setSelected((previous) =>
      previous.includes(permission)
        ? previous.filter((entry) => entry !== permission)
        : [...previous, permission],
    );

  return (
    <div className="flex flex-col gap-4 border-t border-subtle/60 bg-surface/30 px-4 py-4">
      {role.description && !editable && (
        <p className="text-xs text-fg-muted">{role.description}</p>
      )}
      {editable && (
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={100}
          />
          <TextField
            label="Description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={500}
          />
        </div>
      )}
      {isBaseline && (
        <p className="rounded-md border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-fg-secondary">
          Everyone with an account holds these, on every project, without being granted a role
          — so this is the floor under every other role rather than one you assign. Narrowing
          it takes access away instance-wide; widening it hands the permission to every signed-in
          person, including anyone who joins later.
        </p>
      )}
      <PermissionMatrix
        catalog={catalog}
        selected={selected}
        onToggle={permissionsEditable ? toggle : undefined}
      />
      {isBaseline && canManage && <BaselinePreflight selected={selected} />}
      {/* Spec 87: builtin roles are immutable but still grantable instance-wide,
          so this is gated on role.manage, not on `editable`. */}
      <RoleGlobalGrants roleId={role.id} editable={canManage} />
      {(save.isError || remove.isError) && (
        <p className="text-xs text-red-400">{errorMessage(save.error ?? remove.error)}</p>
      )}
      {(editable || (isBaseline && canManage)) && (
        <div className="flex items-center gap-2">
          <RoleImpact roleId={role.id} dirty={dirty} />
          <Button
            onClick={() =>
              // Baseline's name and description are the builtin's; only its
              // permissions travel, which is what the server will accept.
              save.mutate(
                isBaseline
                  ? { permissions: selected }
                  : { name: name.trim(), description: description.trim(), permissions: selected },
              )
            }
            disabled={!dirty || (!isBaseline && !name.trim()) || save.isPending}
          >
            {save.isPending ? "Saving…" : isBaseline ? "Save baseline" : "Save role"}
          </Button>
          <span className="ml-auto" />
          {confirmingDelete ? (
            <Button
              variant="ghost"
              className="text-red-400 hover:text-red-300"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
            >
              {remove.isPending ? "Deleting…" : "Confirm delete?"}
            </Button>
          ) : (
            <Button variant="ghost" onClick={() => setConfirmingDelete(true)}>
              Delete role
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
