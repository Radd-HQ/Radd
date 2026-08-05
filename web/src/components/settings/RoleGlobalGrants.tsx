import { useEffect, useState } from "react";
import { useOnLeaveIds } from "../PersonName";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Users, UsersRound } from "lucide-react";
import { api } from "../../lib/api";
import { apiRoleGlobalGrantsPath } from "../../lib/constants";
import { groupsQuery, queryKeys, roleGlobalGrantsQuery, teamsQuery, usersQuery } from "../../lib/queries";
import type { GlobalGrant } from "../../lib/types";
import { TokenMultiSelect, type TokenOption } from "../TokenMultiSelect";
import { ErrorText } from "../ErrorText";

/**
 * Who holds this role INSTANCE-WIDE (spec 87).
 *
 * Roles could only ever be attached to a project, so the ~47 global-scope atoms
 * in the matrix above (label.create, team.update, sla.*, …) were ungrantable:
 * ticking one changed nothing for anyone but an instance admin. A grant here is
 * what delivers them — and it applies on every project too, so a globally
 * granted role's project atoms are live as well.
 */
export function RoleGlobalGrants({ roleId, editable }: { roleId: string; editable: boolean }) {
  const queryClient = useQueryClient();
  const grants = useQuery(roleGlobalGrantsQuery(roleId));
  const users = useQuery({ ...usersQuery, enabled: editable, retry: false });
  const teams = useQuery(teamsQuery());
  const groups = useQuery(groupsQuery());
  const [draft, setDraft] = useState<GlobalGrant[]>([]);

  // The server owns the state; the draft is only what's on screen between edits.
  useEffect(() => {
    if (grants.data) setDraft(grants.data);
  }, [grants.data]);

  const save = useMutation({
    mutationFn: (rows: GlobalGrant[]) =>
      api.put<GlobalGrant[]>(apiRoleGlobalGrantsPath(roleId), {
        grants: rows.map((row) => ({ user_id: row.user_id, team_id: row.team_id })),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.roleGlobalGrants(roleId) });
      // Effective permissions changed for the grantees — /me drives every gate.
      await queryClient.invalidateQueries({ queryKey: queryKeys.authState });
    },
  });

  // The token select works in "kind:id" strings; map to/from GlobalGrant rows.
  const value = draft.map((row) =>
    row.user_id ? `user:${row.user_id}` : row.team_id ? `team:${row.team_id}` : `group:${row.group_id}`,
  );
  const onLeaveIds = useOnLeaveIds();
  const options: TokenOption[] = [
    ...(teams.data ?? []).map((team) => ({
      value: `team:${team.id}`,
      label: team.name,
      group: "Teams",
      icon: <Users size={12} aria-hidden className="shrink-0 text-accent-text" />,
    })),
    ...(groups.data ?? []).map((g) => ({
      value: `group:${g.id}`,
      label: g.name,
      group: "Directory groups",
      icon: <UsersRound size={12} aria-hidden className="shrink-0 text-accent-text" />,
    })),
    ...(users.data ?? [])
      .filter((u) => u.active)
      .map((u) => ({ value: `user:${u.id}`, label: u.name + (onLeaveIds.has(u.id) ? " (away)" : ""), group: "People" })),
  ];
  const onChangeGrants = (next: string[]) =>
    save.mutate(
      next.map((v) => {
        const [kind, id] = v.split(":");
        return {
          id: "",
          role_id: roleId,
          user_id: kind === "user" ? id : null,
          team_id: kind === "team" ? id : null,
          group_id: kind === "group" ? id : null,
        };
      }),
    );

  return (
    <section aria-label="Instance-wide holders" className="rounded-md border border-subtle p-3">
      <h4 className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
        <Globe size={12} aria-hidden />
        Granted instance-wide
      </h4>
      <p className="mb-2 text-xs text-fg-muted">
        People, teams, and directory groups that hold this role everywhere — the only way a
        non-admin gets a global permission. It also applies inside every project.
      </p>

      {grants.isPending ? (
        <p className="text-xs text-fg-muted">Loading…</p>
      ) : (
        <TokenMultiSelect
          value={value}
          onChange={onChangeGrants}
          options={options}
          disabled={!editable || save.isPending}
          placeholder="Grant to a person or team…"
          ariaLabel="Instance-wide role holders"
        />
      )}
      {save.isError && <ErrorText className="mt-1" error={save.error} />}
    </section>
  );
}
