import { useState } from "react";
import { useOnLeaveIds } from "../PersonName";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, Trash2, UserCog, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import {
  apiTeamManagersPath,
  apiTeamPath,
  apiTeamTransferPath,
} from "../../lib/constants";
import { queryKeys, teamStewardshipQuery, teamByIdQuery, TEAM_STEWARDS_PAGE_SIZE, type PeopleChoice } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import { Permission, type Team } from "../../lib/types";
import { Button } from "../Button";
import { PeopleDirectorySelect } from "../PeopleDirectorySelect";
import { DirectoryPager } from "../DirectoryPager";
import { IconButton } from "../IconButton";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { ErrorText } from "../ErrorText";

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
  onDeleted,
}: {
  team: Team;
  canAdminister: boolean;
  onDeleted?: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [page, setPage] = useState(0);
  const me = useCurrentUser();
  const permissions = usePermissions();
  const stewards = useQuery({ ...teamStewardshipQuery(team.id, page), enabled: canAdminister });
  const total = stewards.data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / TEAM_STEWARDS_PAGE_SIZE) - 1);
  if (stewards.isSuccess && page > lastPage) setPage(lastPage);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.teams });
  const addManager = useMutation({
    mutationFn: (person: PeopleChoice) => api.post<void>(apiTeamManagersPath(team.id), { user_id: person.id }),
    onSuccess: invalidate,
  });
  const removeManager = useMutation({
    mutationFn: (id: string) => api.delete<void>(`${apiTeamManagersPath(team.id)}/${id}`),
    onSuccess: invalidate,
  });
  const transfer = useMutation({
    mutationFn: (person: PeopleChoice) => api.post<Team>(apiTeamTransferPath(team.id), { user_id: person.id }),
    onSuccess: async (updated, person) => {
      // A former owner loses the stewardship-read gate. Cancel its old request
      // before updating authority, and avoid refetching it during that transition.
      await queryClient.cancelQueries({ queryKey: [...queryKeys.teams, "stewardship", team.id] });
      queryClient.setQueryData(teamByIdQuery(team.id).queryKey, updated);
      const keepsAuthority = updated.owner_id === me?.id || permissions.global(Permission.teamUpdate);
      await queryClient.invalidateQueries({ queryKey: queryKeys.teams,
        predicate: query => keepsAuthority || !query.queryKey.includes("stewardship") });
      pushToast(`${team.name} now belongs to ${person.name}`, ToastKind.success);
    },
    onError: (error) => pushToast(errorMessage(error), ToastKind.error),
  });

  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiTeamPath(team.id)),
    onSuccess: async () => {
      pushToast(`${team.name} deleted`, ToastKind.success);
      onDeleted?.();
      await invalidate();
    },
    // A team still attached to a project answers 409 — surface the reason rather
    // than failing silently.
    onError: (error) => pushToast(errorMessage(error), ToastKind.error),
  });

  const onLeaveIds = useOnLeaveIds();
  if (!canAdminister && !team.can_delete) return null;

  const busy = addManager.isPending || removeManager.isPending || transfer.isPending;

  return (
    <section aria-label={`${team.name} ownership`} className="mb-4 rounded-md border border-subtle p-3">
      {canAdminister && <><h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
        <UserCog size={12} aria-hidden />
        Who runs this team
      </h4>

      <div className="flex flex-wrap items-end gap-3">
        <p className="flex items-center gap-1.5 pb-1.5 text-[13px]">
          <Crown size={12} className="text-amber-400/80" aria-hidden />
          {team.owner_id ? (
            <span className="text-fg">{stewards.data?.owner?.name ?? (stewards.isPending ? "Loading owner…" : "Owner unavailable")}</span>
          ) : (
            <span className="text-fg-muted">
              No owner — this team is run by the team admin permission alone
            </span>
          )}
        </p>
        <div className="ml-auto min-w-44">
          <PeopleDirectorySelect kind="person" candidateTeamId={team.id} candidatePurpose="owner"
            label="Transfer ownership" emptyLabel="Transfer ownership…" value={null}
            disabled={busy || !stewards.isSuccess} onChange={person => { if (person) transfer.mutate(person); }} />
        </div>
      </div>

      <p className="mt-3 mb-1 text-[11px] uppercase tracking-wide text-fg-faint">Managers</p>
      {stewards.isPending ? <p className="text-xs text-fg-muted">Loading managers…</p>
        : stewards.isError ? <div className="space-y-2"><ErrorText error={stewards.error} />
          <Button variant="secondary" onClick={() => void stewards.refetch()}>Retry managers</Button></div>
        : <><ul aria-label="Team managers" className="max-h-[35dvh] overflow-y-auto">
          {stewards.data.managers.map(person => <li key={person.id} className="flex items-center gap-2 py-1 text-sm">
            <span className="min-w-0 break-words">{person.name}{onLeaveIds.has(person.id) ? " (away)" : ""}</span>
            {!person.active && <span className="text-xs text-fg-muted">Inactive</span>}
            <IconButton aria-label={`Remove manager ${person.name}`} className="ml-auto shrink-0" danger disabled={busy}
              onClick={() => removeManager.mutate(person.id)}><X size={13} /></IconButton>
          </li>)}
        </ul>
        {!total && <p className="text-xs text-fg-muted">No managers appointed.</p>}
        <DirectoryPager page={page} pageSize={TEAM_STEWARDS_PAGE_SIZE} total={total} busy={stewards.isFetching || busy}
          onPage={setPage} label="managers" />
        <PeopleDirectorySelect kind="person" candidateTeamId={team.id} candidatePurpose="manager"
          label="Add manager" emptyLabel="Add a manager…" value={null} disabled={busy || total >= 50}
          onChange={person => { if (person) addManager.mutate(person); }} />
        {total >= 50 && <p className="mt-1 text-xs text-fg-muted">Up to 50 managers can be appointed. Remove a manager before adding another.</p>}
        </>}
      <p className="mt-1 text-[11px] text-fg-muted">
        Managers needn't be members — a lead can run a team they're not on.
      </p>
      {addManager.isError && <ErrorText className="mt-1" error={addManager.error} />}
      {removeManager.isError && <ErrorText className="mt-1" error={removeManager.error} />}

      </>}
      {team.can_delete && (
        <div className="mt-3 flex items-center gap-2 border-t border-subtle/60 pt-3">
          {confirmingDelete ? (
            <>
              <span className="text-xs text-fg-secondary">Delete {team.name}?</span>
              <Button
                variant="ghost"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
                className="text-status-danger-ink"
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
