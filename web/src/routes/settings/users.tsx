import { Fragment, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ChevronDown, ChevronRight, Lock, UserRound } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { ApiError, api } from "../../lib/api";
import { ApiPath, RoutePath, SEARCH_DEBOUNCE_MS, apiUserPath, apiUserTotpPath } from "../../lib/constants";
import { useCurrentUser, useDebounced, usePermissions } from "../../lib/hooks";
import { INSTANCE_ROLE_LABELS } from "../../lib/meta";
import { USERS_PAGE_SIZE, queryKeys, usersAdminPageQuery, usersAdminQuery } from "../../lib/queries";
import {
  InstanceRole,
  Permission,
  UserSource,
  type InstanceRoleValue,
  type User,
  type UserAdminUpdate,
} from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { useConfirm } from "../../components/ConfirmDialog";
import { SelectField } from "../../components/SelectField";
import { Pager } from "../../components/Pager";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { QueryError } from "../../components/QueryError";
import { SettingsPage } from "../../components/settings/SettingsPage";
import {
  EffectivePermissions,
  ResourceAccessSection,
} from "../../components/settings/AccessInspector";
import { DeleteUserDialog } from "../../components/settings/DeleteUserDialog";
import { DuplicatesSection } from "../../components/settings/UserDuplicates";
import { SOURCE_LABELS, SourceBadge } from "../../components/settings/UserSourceBadge";
import { Table, TBody, Td, THead, Th } from "../../components/Table";
import { RoleGrantsSection } from "../../components/settings/RoleGrantsSection";
import { ErrorText } from "../../components/ErrorText";
import { formatDateTime } from "../../lib/dates";

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
  // RADD-884: the unfiltered query used to render all 3,088 directory rows.
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [debouncedQ, source, active]);
  // Spec 89: the account queued for hard deletion (its dialog owns the confirm).
  const [deleting, setDeleting] = useState<User | null>(null);
  const users = useQuery({
    ...usersAdminPageQuery({ q: debouncedQ, source, active, page }),
    enabled: canView,
    retry: false,
  });
  // Successor candidates need the FULL directory, not the visible page —
  // fetched only while the delete dialog is open (RADD-884).
  const allUsers = useQuery({
    ...usersAdminQuery({}),
    enabled: canView && deleting !== null,
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

  // RADD-1279: the account that lost its authenticator AND its recovery codes.
  const [confirmDialog, confirm] = useConfirm();
  const resetMfa = useMutation({
    mutationFn: (userId: string) => api.delete<void>(apiUserTotpPath(userId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["usersAdmin"] }),
  });
  const onResetMfa = async (user: User) => {
    const ok = await confirm({
      title: `Reset two-factor for ${user.name}?`,
      message: (
        <>
          Their authenticator and recovery codes stop working. At their next password
          sign-in they set up two-factor again — or, if this server does not require it,
          sign in with their password alone. Use this when they have lost both.
        </>
      ),
      confirmLabel: "Reset two-factor",
      danger: true,
    });
    if (ok) resetMfa.mutate(user.id);
  };

  const forbidden = users.error instanceof ApiError && users.error.status === 403;
  const list = users.data?.rows ?? [];
  const total = users.data?.total ?? null;

  return (
    <SettingsPage history={{ entities: ["user"] }}
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
              busy={patchUser.isPending || resetMfa.isPending}
              onResetMfa={(user) => void onResetMfa(user)}
              onDelete={setDeleting}
              onViewAs={async (user) => {
                // RADD-836 U1: a full reload swaps every client cache to the
                // previewed account; the server enforces read-only.
                await api.post(ApiPath.viewAs, { user_id: user.id });
                window.location.assign("/");
              }}
            />
          )}
          {total !== null && total > USERS_PAGE_SIZE && (
            <div className="mt-3 flex justify-end">
              <Pager
                page={page}
                pageCount={Math.ceil(total / USERS_PAGE_SIZE)}
                total={total}
                onPage={setPage}
              />
            </div>
          )}
          {patchUser.isError && (
            <ErrorText className="mt-2" error={patchUser.error} />
          )}
          {resetMfa.isError && <ErrorText className="mt-2" error={resetMfa.error} />}
          {confirmDialog}
          {isInstanceAdmin && <DuplicatesSection />}
          {deleting && (
            <DeleteUserDialog
              user={deleting}
              candidates={(allUsers.data ?? []).filter((u) => u.id !== deleting.id && u.active)}
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
  onViewAs,
  onResetMfa,
  busy,
}: {
  users: User[];
  meId: string;
  isInstanceAdmin: boolean;
  onToggleActive: (user: User) => void;
  onChangeRole: (userId: string, role: InstanceRoleValue) => void;
  onDelete: (user: User) => void;
  onViewAs: (user: User) => Promise<void>;
  onResetMfa: (user: User) => void;
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
            <Th>Two-factor</Th>
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
                  <TwoFactorCell
                    user={user}
                    canReset={isInstanceAdmin && !self}
                    busy={busy}
                    onReset={() => onResetMfa(user)}
                  />
                </Td>
                <Td>
                  {user.last_login_at ? (
                    formatDateTime(user.last_login_at)
                  ) : (
                    <span className="text-fg-faint">Never</span>
                  )}
                </Td>
                {isInstanceAdmin && (
                  <Td>
                    {/* RADD-836 U1: read-only preview — the server refuses every
                        write while it's on; a full reload swaps every cache. */}
                    {!self && user.active && (
                      <button
                        type="button"
                        onClick={() => void onViewAs(user)}
                        disabled={busy}
                        className="mr-1.5 rounded border border-strong px-2 py-0.5 text-[11px] text-fg-secondary hover:border-accent hover:text-accent-text cursor-pointer disabled:opacity-50"
                        title="See the app exactly as this person does (read-only)"
                      >
                        View as
                      </button>
                    )}
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
                  <Td colSpan={isInstanceAdmin ? 9 : 8} className="bg-surface/40">
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
                      <ResourceAccessSection userId={user.id} />
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
 * RADD-1279: whether the person's PASSWORD sign-in has a second factor.
 * Directory and SSO accounts get theirs from the identity provider, which
 * Radd cannot see — said plainly instead of reading as "Off".
 */
function TwoFactorCell({
  user,
  canReset,
  busy,
  onReset,
}: {
  user: User;
  canReset: boolean;
  busy: boolean;
  onReset: () => void;
}) {
  if (user.mfa_enabled) {
    return (
      <span className="inline-flex items-center gap-1.5" data-mfa-cell="on">
        <span className="text-fg">On</span>
        {canReset && (
          <button
            type="button"
            onClick={onReset}
            disabled={busy}
            className="rounded border border-strong px-2 py-0.5 text-[11px] text-fg-secondary hover:border-red-500/50 hover:text-red-400 cursor-pointer disabled:opacity-50"
            title="For someone who lost both their authenticator and their recovery codes"
          >
            Reset
          </button>
        )}
      </span>
    );
  }
  if (user.source === UserSource.ldap || user.source === UserSource.oidc) {
    return (
      <span className="text-fg-faint" title="Set at the identity provider" data-mfa-cell="idp">
        Identity provider
      </span>
    );
  }
  return <span className="text-fg-muted" data-mfa-cell="off">Off</span>;
}

// EffectivePermissions / ResourceAccessSection moved to
// components/settings/AccessInspector.tsx (RADD-809): the atom half gained a
// scope picker + provenance + role backlinks, and the spec-92 resource half
// joined it — one file for the whole inspector, shared with the Teams panel.
