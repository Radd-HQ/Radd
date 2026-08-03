import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ChevronDown, ChevronRight, Lock, UserRound } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { ApiError, api, errorMessage } from "../../lib/api";
import { RoutePath, SEARCH_DEBOUNCE_MS, apiUserPath } from "../../lib/constants";
import { useCurrentUser, useDebounced, usePermissions } from "../../lib/hooks";
import { INSTANCE_ROLE_LABELS } from "../../lib/meta";
import { queryKeys, userPermissionsQuery, usersAdminQuery } from "../../lib/queries";
import {
  InstanceRole,
  Permission,
  UserSource,
  type InstanceRoleValue,
  type User,
  type UserAdminUpdate,
} from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { SelectField } from "../../components/SelectField";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { QueryError } from "../../components/QueryError";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { DeleteUserDialog } from "../../components/settings/DeleteUserDialog";
import { DuplicatesSection } from "../../components/settings/UserDuplicates";
import { SOURCE_LABELS, SourceBadge } from "../../components/settings/UserSourceBadge";
import { Table, TBody, Td, THead, Th } from "../../components/Table";
import { RoleGrantsSection } from "../../components/settings/RoleGrantsSection";

/**
 * THE people page (spec 84; spec 86 collapsed the membership layer): every
 * account with its auth source, activity, last sign-in — and the server-wide
 * role ladder inline: `users.instance_role` (admin|member) via
 * PATCH /users/{id}.
 *
 * Gating:
 * - Viewing needs global manage or instance admin; GET /users itself is gated
 *   `user.manage`.
 * - Role changes + activate/deactivate are instance admin, enforced by the API
 *   (403; self-demotion 409) and hidden here, incl. the client-side self-row
 *   guard (locking yourself out via your own row is a footgun — block it).
 * - Duplicates/merge stay instance admin. The AD import affordances live in
 *   Settings → Directory (spec 85) — pointer only.
 */
export function UsersSettingsPage() {
  const me = useCurrentUser();
  const perms = usePermissions();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;
  const canView = isInstanceAdmin || perms.global(Permission.globalManage);
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const debouncedQ = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const [source, setSource] = useState("");
  const [active, setActive] = useState("");
  // Spec 89: the account queued for hard deletion (its dialog owns the confirm).
  const [deleting, setDeleting] = useState<User | null>(null);
  const users = useQuery({
    ...usersAdminQuery({ q: debouncedQ, source, active }),
    enabled: canView,
    retry: false,
  });

  const patchUser = useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: UserAdminUpdate }) =>
      api.patch<User>(apiUserPath(userId), body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["usersAdmin"] });
      await queryClient.invalidateQueries({ queryKey: queryKeys.users });
      await queryClient.invalidateQueries({ queryKey: queryKeys.userDuplicates });
    },
  });

  const forbidden = users.error instanceof ApiError && users.error.status === 403;
  const list = users.data ?? [];

  return (
    <SettingsPage
      title="Users"
      description="Every account on this server — auth source, activity, last sign-in — plus the server-wide role. Deactivating revokes sessions and blocks all sign-in paths."
      actions={
        isInstanceAdmin ? (
          <Link
            to={RoutePath.settingsDirectory}
            className="flex items-center gap-1 text-[13px] text-accent-text hover:text-accent-text-strong"
          >
            Import from AD → Directory settings
            <ArrowRight size={13} aria-hidden />
          </Link>
        ) : undefined
      }
    >
      {!canView || forbidden ? (
        <EmptyState icon={Lock} message="Only admins can administer users." />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1">
              <TextField
                label="Search"
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="Email or name…"
              />
            </div>
            <SelectField
              label="Source"
              value={source}
              onChange={(event) => setSource(event.target.value)}
            >
              <option value="">All sources</option>
              {Object.values(UserSource).map((value) => (
                <option key={value} value={value}>
                  {SOURCE_LABELS[value]}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Status"
              value={active}
              onChange={(event) => setActive(event.target.value)}
            >
              <option value="">All</option>
              <option value="true">Active</option>
              <option value="false">Deactivated</option>
            </SelectField>
          </div>
          {users.isPending ? (
            <TableSkeleton rows={5} />
          ) : users.isError ? (
            <QueryError label="users" error={users.error} />
          ) : list.length === 0 ? (
            <EmptyState icon={UserRound} message="No users match." />
          ) : (
            <UsersTable
              users={list}
              meId={me?.id ?? ""}
              isInstanceAdmin={isInstanceAdmin}
              onToggleActive={(user) =>
                patchUser.mutate({ userId: user.id, body: { active: !user.active } })
              }
              onChangeRole={(userId, role) =>
                patchUser.mutate({ userId, body: { instance_role: role } })
              }
              busy={patchUser.isPending}
              onDelete={setDeleting}
            />
          )}
          {patchUser.isError && (
            <p className="mt-2 text-xs text-red-400">{errorMessage(patchUser.error)}</p>
          )}
          {isInstanceAdmin && <DuplicatesSection />}
          {deleting && (
            <DeleteUserDialog
              user={deleting}
              candidates={(users.data ?? []).filter((u) => u.id !== deleting.id && u.active)}
              onClose={() => setDeleting(null)}
            />
          )}
        </>
      )}
    </SettingsPage>
  );
}

function UsersTable({
  users,
  meId,
  isInstanceAdmin,
  onToggleActive,
  onChangeRole,
  onDelete,
  busy,
}: {
  users: User[];
  meId: string;
  isInstanceAdmin: boolean;
  onToggleActive: (user: User) => void;
  onChangeRole: (userId: string, role: InstanceRoleValue) => void;
  onDelete: (user: User) => void;
  busy: boolean;
}) {
  // Which person's roles are open. One at a time: the grants editor fetches
  // per subject, and a table of them expanded at once would be a query per row.
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <div className="overflow-x-auto rounded-lg border border-subtle">
      <Table>
        <THead>
          <tr>
            <Th />
            <Th>Email</Th>
            <Th>Name</Th>
            <Th>Source</Th>
            <Th>Instance access</Th>
            <Th>Status</Th>
            <Th>Last login</Th>
            {isInstanceAdmin && <Th />}
          </tr>
        </THead>
        <TBody>
          {users.map((user) => {
            const self = user.id === meId;
            const open = openId === user.id;
            return (
              <Fragment key={user.id}>
              <tr>
                <Td className="w-6">
                  {/* RADD-775: roles a person HOLDS live here — instance access
                      (the column beside) is a different thing from a role. */}
                  <button
                    type="button"
                    onClick={() => setOpenId(open ? null : user.id)}
                    aria-expanded={open}
                    aria-label={`Roles held by ${user.name}`}
                    title="Roles held"
                    className="rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                  >
                    {open ? (
                      <ChevronDown size={14} aria-hidden />
                    ) : (
                      <ChevronRight size={14} aria-hidden />
                    )}
                  </button>
                </Td>
                <Td className="text-heading">{user.email}</Td>
                <Td>{user.name}</Td>
                <Td>
                  <SourceBadge source={user.source} />
                </Td>
                <Td>
                  {isInstanceAdmin && !self ? (
                    // A switch, not a dropdown (RADD-776). The column has two
                    // values and behaves as a boolean; naming them invited
                    // reading it as a role ladder with more rungs, which is
                    // exactly the confusion RADD-775 set out to remove.
                    <label className="inline-flex cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={user.instance_role === InstanceRole.admin}
                        disabled={busy}
                        onChange={(event) =>
                          onChangeRole(
                            user.id,
                            (event.target.checked
                              ? InstanceRole.admin
                              : InstanceRole.member) as InstanceRoleValue,
                          )
                        }
                        aria-label={`Instance administrator: ${user.name}`}
                        title="An instance administrator bypasses every permission check."
                        className="size-3.5 cursor-pointer accent-[var(--accent-fill)]"
                      />
                      <span className="text-[11px] text-fg-secondary">Administrator</span>
                    </label>
                  ) : (
                    <span
                      className={
                        "rounded border px-1.5 py-px text-[11px] " +
                        (user.instance_role === InstanceRole.admin
                          ? "border-accent/50 text-accent-text"
                          : "border-strong text-fg-secondary")
                      }
                    >
                      {INSTANCE_ROLE_LABELS[user.instance_role]}
                    </span>
                  )}
                </Td>
                <Td>
                  {user.active ? (
                    <span className="text-fg-muted">Active</span>
                  ) : (
                    <span className="text-red-400">Deactivated</span>
                  )}
                </Td>
                <Td>
                  {user.last_login_at ? (
                    new Date(user.last_login_at).toLocaleString()
                  ) : (
                    <span className="text-fg-faint">Never</span>
                  )}
                </Td>
                {isInstanceAdmin && (
                  <Td>
                    {!self && (
                      <button
                        type="button"
                        onClick={() => onToggleActive(user)}
                        disabled={busy}
                        className={
                          "rounded border px-2 py-0.5 text-[11px] cursor-pointer disabled:opacity-50 " +
                          (user.active
                            ? "border-strong text-fg-secondary hover:border-red-500/50 hover:text-red-400"
                            : "border-strong text-fg-secondary hover:border-emerald-500/50 hover:text-emerald-300")
                        }
                      >
                        {user.active ? "Deactivate" : "Activate"}
                      </button>
                    )}
                    {/* Spec 89: hard delete — the dialog shows what the account
                        owns and asks who inherits it before anything happens. */}
                    {!self && (
                      <button
                        type="button"
                        onClick={() => onDelete(user)}
                        disabled={busy}
                        className="ml-1.5 rounded border border-strong px-2 py-0.5 text-[11px] text-fg-secondary hover:border-red-500/50 hover:text-red-400 cursor-pointer disabled:opacity-50"
                      >
                        Delete
                      </button>
                    )}
                  </Td>
                )}
              </tr>
              {open && (
                <tr>
                  <Td colSpan={isInstanceAdmin ? 7 : 6} className="bg-surface/40">
                    <div className="flex flex-col gap-3 px-2 py-3">
                      <p className="text-xs text-fg-muted">
                        Roles this person holds, each applying instance-wide or on the projects
                        you pick. Separate from <strong>instance access</strong> above (an admin
                        bypasses every permission check) and from the{" "}
                        <strong>Baseline</strong> role, which everyone holds without being
                        granted anything.
                      </p>
                      {/* The same editor the Teams panel uses — its `subject`
                          has always accepted a userId; nothing mounted it. */}
                      <RoleGrantsSection
                        subject={{ userId: user.id }}
                        canManage={isInstanceAdmin}
                      />
                      <EffectivePermissions userId={user.id} />
                    </div>
                  </Td>
                </tr>
              )}
              </Fragment>
            );
          })}
        </TBody>
      </Table>
    </div>
  );
}


/**
 * What this person can actually do, and why (RADD-779).
 *
 * The listed grants above say what was HANDED OUT. This says what it RESOLVES
 * to — including the spec-50 umbrella expansions that turn one ticked
 * `cycle.manage` into four held atoms, which is the step that made "why can this
 * member delete cycles?" unanswerable by reading the screen.
 *
 * Resolved on the server, never here: re-implementing umbrella expansion, the
 * admin short-circuit and key-scope narrowing in the client would produce a
 * second opinion, and the one that disagrees with the resolver is the one
 * people would be reading.
 */
function EffectivePermissions({ userId }: { userId: string }) {
  const { data, isPending, isError, error } = useQuery(userPermissionsQuery(userId));

  if (isPending) return <p className="text-xs text-fg-muted">Resolving permissions…</p>;
  if (isError) return <p className="text-xs text-red-400">{errorMessage(error)}</p>;

  const rows = data ?? [];
  const admin = rows.find((row) => row.kind === "instance-admin");
  if (admin) {
    return (
      <p className="rounded-md border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-fg-secondary">
        <strong className="text-heading">Everything.</strong> An instance administrator bypasses
        every permission check, so no role or grant applies — switch Administrator off to make
        the rules below take effect.
      </p>
    );
  }

  // Group by where it came from, so the answer reads as "Baseline gives them X,
  // the Member role adds Y" rather than an undifferentiated wall of atoms.
  const bySource = new Map<string, typeof rows>();
  for (const row of rows) {
    const key = row.kind === "baseline" ? "Baseline" : (row.role_name ?? "Granted role");
    const list = bySource.get(key) ?? [];
    list.push(row);
    bySource.set(key, list);
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
        Effective permissions ({rows.length})
      </p>
      {rows.length === 0 ? (
        <p className="text-xs text-fg-muted">
          None — this account cannot do anything until Baseline or a granted role gives it
          something.
        </p>
      ) : (
        [...bySource.entries()].map(([source, atoms]) => (
          <div key={source} className="flex flex-wrap items-baseline gap-1.5">
            <span className="shrink-0 text-[11px] font-medium text-fg-secondary">{source}</span>
            {atoms.map((atom) => (
              <span
                key={atom.permission}
                title={
                  atom.implied
                    ? `Implied by an umbrella permission, not ticked directly on ${source}.`
                    : `Granted directly by ${source}.`
                }
                className={
                  "rounded border px-1 font-mono text-[10px] " +
                  (atom.implied
                    ? "border-subtle text-fg-muted"
                    : "border-strong text-fg-secondary")
                }
              >
                {atom.permission}
              </span>
            ))}
          </div>
        ))
      )}
      <p className="text-[10px] text-fg-faint">
        Dimmed atoms are implied by an umbrella (project.manage implies state.create), not
        ticked on the role itself.
      </p>
    </div>
  );
}
