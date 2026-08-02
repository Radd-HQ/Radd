import { useState } from "react";
import { useOnLeaveIds } from "../PersonName";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, Trash2, UserCog } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import {
  apiTeamManagersPath,
  apiTeamPath,
  apiTeamTransferPath,
} from "../../lib/constants";
import { queryKeys, usersQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import type { Team, TeamManagersUpdate } from "../../lib/types";
import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { TokenMultiSelect } from "../TokenMultiSelect";

/**
 * Team ownership + managers (spec 87) — the per-team delegation surface.
 *
 * Managers administer THIS team: they edit its roster and rename it. They can't
 * appoint further managers, transfer it, delete it, or attach it to a project —
 * so delegating a team never leaks the ability to widen what that team can do.
 * Shown to the owner and to holders of the global team atoms.
 */
export function TeamStewardship({
  team,
  canAdminister,
}: {
  team: Team;
  canAdminister: boolean;
}) {
  const queryClient = useQueryClient();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const users = useQuery({ ...usersQuery, enabled: canAdminister, retry: false });

  const nameOf = (userId: string) =>
    (users.data ?? []).find((u) => u.id === userId)?.name ?? "Someone";

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.teams });

  const setManagers = useMutation({
    mutationFn: (body: TeamManagersUpdate) =>
      api.put<Team>(apiTeamManagersPath(team.id), body),
    onSuccess: async () => {
      await invalidate();
    },
  });

  const transfer = useMutation({
    mutationFn: (userId: string) =>
      api.post<Team>(apiTeamTransferPath(team.id), { user_id: userId }),
    onSuccess: async (updated) => {
      pushToast(`${team.name} now belongs to ${nameOf(updated.owner_id ?? "")}`, ToastKind.success);
      await invalidate();
    },
    onError: (error) => pushToast(errorMessage(error), ToastKind.error),
  });

  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiTeamPath(team.id)),
    onSuccess: async () => {
      pushToast(`${team.name} deleted`, ToastKind.success);
      await invalidate();
    },
    // A team still attached to a project answers 409 — surface the reason rather
    // than failing silently.
    onError: (error) => pushToast(errorMessage(error), ToastKind.error),
  });

  if (!canAdminister) return null;

  const candidates = (users.data ?? []).filter(
    (u) => u.active && u.id !== team.owner_id && !team.managers.includes(u.id),
  );
  // Options for the managers token select: all active users (bar the owner) so current managers
  // resolve to their name; the token select hides already-chosen ones from its dropdown.
  const onLeaveIds = useOnLeaveIds();
  const managerOptions = (users.data ?? [])
    .filter((u) => u.active && u.id !== team.owner_id)
    .map((u) => ({ value: u.id, label: u.name + (onLeaveIds.has(u.id) ? " (away)" : "") }));

  return (
    <section aria-label={`${team.name} ownership`} className="mb-4 rounded-md border border-subtle p-3">
      <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
        <UserCog size={12} aria-hidden />
        Who runs this team
      </h4>

      <div className="flex flex-wrap items-end gap-3">
        <p className="flex items-center gap-1.5 pb-1.5 text-[13px]">
          <Crown size={12} className="text-amber-400/80" aria-hidden />
          {team.owner_id ? (
            <span className="text-fg">{nameOf(team.owner_id)}</span>
          ) : (
            <span className="text-fg-muted">
              No owner — this team is run by the team admin permission alone
            </span>
          )}
        </p>
        <div className="ml-auto min-w-44">
          <SelectField
            label="Transfer ownership"
            value=""
            disabled={transfer.isPending}
            onChange={(event) => event.target.value && transfer.mutate(event.target.value)}
          >
            <option value="">Choose a user…</option>
            {candidates.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </SelectField>
        </div>
      </div>

      <p className="mt-3 mb-1 text-[11px] uppercase tracking-wide text-fg-faint">Managers</p>
      <TokenMultiSelect
        value={team.managers}
        onChange={(ids) => setManagers.mutate({ user_ids: ids })}
        options={managerOptions}
        disabled={setManagers.isPending}
        placeholder="Add a manager…"
        ariaLabel={`Managers of ${team.name}`}
      />
      <p className="mt-1 text-[11px] text-fg-muted">
        Managers needn't be members — a lead can run a team they're not on.
      </p>
      {setManagers.isError && (
        <p className="mt-1 text-xs text-red-400">{errorMessage(setManagers.error)}</p>
      )}

      {team.can_delete && (
        <div className="mt-3 flex items-center gap-2 border-t border-subtle/60 pt-3">
          {confirmingDelete ? (
            <>
              <span className="text-xs text-fg-secondary">Delete {team.name}?</span>
              <Button
                variant="ghost"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
                className="text-red-400"
              >
                {remove.isPending ? "Deleting…" : "Yes, delete"}
              </Button>
              <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button variant="ghost" onClick={() => setConfirmingDelete(true)}>
              <Trash2 size={13} aria-hidden />
              Delete team
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
