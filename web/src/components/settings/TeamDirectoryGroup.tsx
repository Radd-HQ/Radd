import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderSync, Plus, TriangleAlert, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiTeamDirectorySyncPath, apiTeamGroupPath, apiTeamGroupsPath } from "../../lib/constants";
import { groupsQuery, queryKeys, teamGroupsQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import type { DirectorySyncResult, RaddGroup, Team, TeamGroup } from "../../lib/types";
import { Button } from "../Button";

/**
 * The team's GROUP members (RADD-829). A team is always local now; it reaches
 * the directory by HOLDING mirrored AD groups, whose people (nesting included)
 * count as members. Mirroring a new group from AD happens on Settings →
 * Directory (the import); this section picks from the already-mirrored list.
 */
export function TeamGroupsSection({ team, canManage }: { team: Team; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [picking, setPicking] = useState(false);
  const memberGroups = useQuery(teamGroupsQuery(team.id));
  const allGroups = useQuery({ ...groupsQuery(), enabled: picking });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.teams });
    await queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(team.id) });
    await queryClient.invalidateQueries({ queryKey: [...queryKeys.teams, team.id, "groups"] });
  };

  const addGroup = useMutation({
    mutationFn: (groupId: string) =>
      api.post<TeamGroup>(apiTeamGroupsPath(team.id), { group_id: groupId }),
    onSuccess: async () => {
      setPicking(false);
      await invalidate();
    },
  });

  const removeGroup = useMutation({
    mutationFn: (groupId: string) => api.delete(apiTeamGroupPath(team.id, groupId)),
    onSuccess: invalidate,
  });

  const syncNow = useMutation({
    mutationFn: () => api.post<DirectorySyncResult>(apiTeamDirectorySyncPath(team.id), {}),
    onSuccess: async (result) => {
      pushToast(`${team.name}: +${result.added} / −${result.removed}`, ToastKind.success);
      await invalidate();
    },
  });

  const held = memberGroups.data ?? [];
  const heldIds = new Set(held.map((g) => g.group_id));
  const addable = (allGroups.data ?? []).filter((g: RaddGroup) => !heldIds.has(g.id));
  if (held.length === 0 && !canManage) return null;

  return (
    <section aria-label={`${team.name} directory groups`} className="mb-4">
      <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
        Directory groups
      </h4>
      {held.length > 0 && (
        <ul className="mb-2 flex flex-col gap-1.5">
          {held.map((group) => (
            <li key={group.group_id} className="flex flex-wrap items-center gap-2 text-[13px]">
              <span
                className="rounded border border-sky-500/50 px-1.5 py-px text-[11px] text-sky-300"
                title={group.dn}
              >
                {group.name}
              </span>
              {group.directory_missing_since && (
                <span
                  className="flex items-center gap-1 text-[11px] text-amber-300"
                  title={`Last seen ${new Date(group.directory_missing_since).toLocaleString()} — renamed, moved, or deleted in AD. Its people are kept and the sync won't remove anyone while it's missing.`}
                >
                  <TriangleAlert size={12} aria-hidden />
                  missing from AD
                </span>
              )}
              {canManage && (
                <button
                  type="button"
                  onClick={() => removeGroup.mutate(group.group_id)}
                  disabled={removeGroup.isPending}
                  aria-label={`Remove ${group.name} from ${team.name}`}
                  className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-50"
                >
                  <X size={13} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {held.length > 0 && (
        <p className="mb-2 text-xs text-fg-muted">
          These groups' people (nested groups included) count as members of this team.
        </p>
      )}
      {canManage && (
        <div className="flex flex-wrap items-center gap-2">
          {held.length > 0 && (
            <Button variant="ghost" onClick={() => syncNow.mutate()} disabled={syncNow.isPending}>
              <FolderSync size={13} aria-hidden />
              {syncNow.isPending ? "Syncing…" : "Sync now"}
            </Button>
          )}
          {picking ? (
            <div className="flex w-full max-w-md flex-col gap-2">
              {allGroups.isError ? (
                <p className="text-xs text-red-400">{errorMessage(allGroups.error)}</p>
              ) : allGroups.isPending ? (
                <p className="text-xs text-fg-muted">Loading groups…</p>
              ) : addable.length === 0 ? (
                <p className="text-xs text-fg-muted">
                  No mirrored groups to add — import one on Settings → Directory first.
                </p>
              ) : (
                <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
                  {addable.map((group: RaddGroup) => (
                    <li key={group.id}>
                      <button
                        type="button"
                        onClick={() => addGroup.mutate(group.id)}
                        disabled={addGroup.isPending}
                        className="flex w-full items-center gap-2 rounded-md border border-subtle px-2.5 py-1.5 text-left text-[13px] hover:bg-surface/60 cursor-pointer disabled:opacity-50"
                      >
                        <span className="truncate text-fg">{group.name}</span>
                        <span className="ml-auto shrink-0 text-xs text-fg-muted">
                          {group.direct_member_count} direct
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div>
                <Button variant="ghost" onClick={() => setPicking(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button variant="ghost" onClick={() => setPicking(true)}>
              <Plus size={13} aria-hidden />
              Add a group
            </Button>
          )}
        </div>
      )}
      {(addGroup.isError || removeGroup.isError || syncNow.isError) && (
        <p className="mt-1 text-xs text-red-400">
          {errorMessage(addGroup.error ?? removeGroup.error ?? syncNow.error)}
        </p>
      )}
    </section>
  );
}
