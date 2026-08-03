import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Plus, ShieldCheck } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiRolePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { permissionsCatalogQuery, queryKeys, rolesQuery } from "../../lib/queries";
import {
  BASELINE_ROLE_KEY,
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
  const canManage = perms.global(Permission.roleManage);
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
      {/* Spec 87: builtin roles are immutable but still grantable instance-wide,
          so this is gated on role.manage, not on `editable`. */}
      <RoleGlobalGrants roleId={role.id} editable={canManage} />
      {(save.isError || remove.isError) && (
        <p className="text-xs text-red-400">{errorMessage(save.error ?? remove.error)}</p>
      )}
      {(editable || (isBaseline && canManage)) && (
        <div className="flex items-center gap-2">
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
