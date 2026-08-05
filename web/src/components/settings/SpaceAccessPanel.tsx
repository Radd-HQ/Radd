import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, ShieldCheck, Users, User as UserIcon, X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { queryKeys, roleGrantsQuery, rolesQuery, teamsQuery, usersQuery } from "../../lib/queries";
import { GrantSubject, type RoleGrantCreate } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { SubjectPicker, type Subject } from "./SubjectPicker";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";

/**
 * Who has access to ONE wiki space, and the way to give it (RADD-793).
 *
 * RADD-791 made a space a grant scope; without a screen that would be an
 * API-only feature, and spec 87's lesson is that an ungrantable permission is a
 * dead one — all 47 global atoms were unreachable for a year because nothing
 * could deliver them.
 *
 * The panel lists only the grants BOUND to this space. Instance-wide wiki roles
 * also apply here and are deliberately absent: this answers "who was given
 * access to this space", and showing a global grant in a per-space list would
 * offer a Revoke button that takes access away everywhere.
 */
export function SpaceAccessPanel({
  spaceId,
  spaceName,
  canManage,
}: {
  spaceId: string;
  spaceName: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const grants = useQuery(roleGrantsQuery({ spaceId }));
  const roles = useQuery(rolesQuery());
  const teams = useQuery(teamsQuery());
  // `retry: false` — a manager without user.manage gets a 403 here and the
  // panel still has to render; names fall back to the id-less placeholder.
  const directory = useQuery({ ...usersQuery, retry: false });
  const [granting, setGranting] = useState(false);

  const roleName = new Map((roles.data ?? []).map((r) => [r.id, r.name]));
  const teamName = new Map((teams.data ?? []).map((t) => [t.id, t.name]));
  const userName = new Map((directory.data ?? []).map((u) => [u.id, u.name]));

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.roleGrants });
  const revoke = useMutation({
    mutationFn: (grantId: string) => api.delete(`${ApiPath.roleGrants}/${grantId}`),
    onSuccess: invalidate,
  });

  const list = grants.data ?? [];

  return (
    <div className="mt-2 rounded-md border border-subtle bg-surface/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <h5 className="text-[11px] font-medium uppercase tracking-wide text-fg-faint">
          Access
        </h5>
        {canManage && (
          <Button variant="ghost" size="sm" onClick={() => setGranting(true)}>
            <Plus size={12} aria-hidden />
            Grant role
          </Button>
        )}
      </div>

      {list.length === 0 ? (
        <p className="text-xs text-fg-muted">
          No space-specific grants — only instance-wide wiki roles reach this space.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {list.map((grant) => (
            <li key={grant.id} className="flex items-center gap-2 text-[13px]">
              <ShieldCheck size={12} className="text-fg-faint" aria-hidden />
              <span className="text-fg">{roleName.get(grant.role_id) ?? "role"}</span>
              <span className="inline-flex items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] text-fg-secondary">
                {grant.team_id ? (
                  <>
                    <Users size={10} aria-hidden />
                    {teamName.get(grant.team_id) ?? "team"}
                  </>
                ) : (
                  <>
                    <UserIcon size={10} aria-hidden />
                    {userName.get(grant.user_id ?? "") ?? "user"}
                  </>
                )}
              </span>
              {canManage && (
                <IconButton
                  danger
                  onClick={() => revoke.mutate(grant.id)}
                  disabled={revoke.isPending}
                  aria-label="Revoke grant"
                  className="ml-auto"
                >
                  <X size={13} />
                </IconButton>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-2 flex items-center gap-1 text-[11px] text-fg-faint">
        <Globe size={10} aria-hidden />
        Instance-wide wiki roles apply here too and are managed under Roles.
      </p>

      {granting && (
        <GrantSpaceRoleDialog
          spaceId={spaceId}
          spaceName={spaceName}
          onClose={() => setGranting(false)}
          onGranted={invalidate}
        />
      )}
    </div>
  );
}

function GrantSpaceRoleDialog({
  spaceId,
  spaceName,
  onClose,
  onGranted,
}: {
  spaceId: string;
  spaceName: string;
  onClose: () => void;
  onGranted: () => void;
}) {
  const roles = useQuery(rolesQuery());
  const [roleId, setRoleId] = useState("");
  const teams = useQuery(teamsQuery());
  const users = useQuery({ ...usersQuery, retry: false });
  const [subject, setSubject] = useState<Subject | null>(null);
  // Users and teams only: a role-subject grant here would mean "this role, in
  // this space, for whoever holds that role" — which is the grant itself.
  const subjects = useMemo<Subject[]>(
    () => [
      ...(teams.data ?? []).map((t) => ({ type: GrantSubject.team, id: t.id, name: t.name })),
      ...(users.data ?? []).map((u) => ({ type: GrantSubject.user, id: u.id, name: u.name })),
    ],
    [teams.data, users.data],
  );

  const grant = useMutation({
    mutationFn: () => {
      const body: RoleGrantCreate = {
        role_id: roleId,
        space_ids: [spaceId],
        ...(subject?.type === GrantSubject.team
          ? { team_id: subject.id }
          : { user_id: subject?.id }),
      };
      return api.post(ApiPath.roleGrants, body);
    },
    onSuccess: () => {
      onGranted();
      onClose();
    },
  });

  return (
    <Modal title={`Grant access to ${spaceName}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          grant.mutate();
        }}
        className="flex flex-col gap-4"
      >
        <div>
          <p className="mb-1.5 text-xs font-medium text-fg-secondary">Who</p>
          <SubjectPicker subjects={subjects} value={subject} onChange={setSubject} />
        </div>

        <SelectField label="Role" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
          <option value="">Choose a role…</option>
          {(roles.data ?? []).map((role) => (
            <option key={role.id} value={role.id}>
              {role.name}
            </option>
          ))}
        </SelectField>

        <p className="text-[11px] text-fg-faint">
          The role applies in this space only. A read-only space is a role holding page.read;
          add page.write to let them edit, comment.write to let them discuss.
        </p>

        {grant.isError && <ErrorText error={grant.error} />}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!roleId || !subject || grant.isPending}>
            {grant.isPending ? "Granting…" : "Grant"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
