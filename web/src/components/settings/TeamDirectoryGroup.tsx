import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderSync, Link2, TriangleAlert, Unlink, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import {
  SEARCH_DEBOUNCE_MS,
  apiTeamDirectorySyncPath,
  apiTeamPath,
} from "../../lib/constants";
import { useCurrentUser, useDebounced } from "../../lib/hooks";
import { instanceStatusQuery, ldapGroupsQuery, queryKeys } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import {
  InstanceRole,
  type DirectorySyncResult,
  type Team,
  type TeamUpdate,
} from "../../lib/types";
import { Button } from "../Button";
import { TextField } from "../TextField";

/**
 * Team ↔ AD group link (spec 84): shows the linked CN with unlink + "Sync now"
 * (returns +added / −removed), or — for instance admins with a bind account —
 * a group search picker. Nested AD membership counts (transitive rule).
 */
export function TeamDirectoryGroup({ team }: { team: Team }) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const [picking, setPicking] = useState(false);
  // The AD affordances key on the bind-account status flag; the status (and
  // group-search) endpoints are instance-admin only, so a plain team manager
  // just sees the linked CN — never a 403 toast.
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;
  const status = useQuery({ ...instanceStatusQuery, enabled: isInstanceAdmin, retry: false });
  const directoryReady = Boolean(status.data?.ldap_bind_account);
  const groups = useQuery({ ...ldapGroupsQuery(debounced), enabled: picking && directoryReady });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.teams });
    await queryClient.invalidateQueries({ queryKey: queryKeys.teamMembers(team.id) });
  };

  const patchTeam = useMutation({
    mutationFn: (body: TeamUpdate) => api.patch<Team>(apiTeamPath(team.id), body),
    onSuccess: async () => {
      setPicking(false);
      setQ("");
      await invalidate();
    },
  });

  const syncNow = useMutation({
    mutationFn: () => api.post<DirectorySyncResult>(apiTeamDirectorySyncPath(team.id), {}),
    onSuccess: async (result) => {
      pushToast(`${team.name}: +${result.added} / −${result.removed}`, ToastKind.success);
      await invalidate();
    },
  });

  if (!team.directory_group_dn && !directoryReady) return null;

  return (
    <section aria-label={`${team.name} directory group`} className="mb-4">
      <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
        Directory group
      </h4>
      {team.directory_missing_since && (
        <div className="mb-2 rounded-md border border-amber-500/50 bg-amber-500/5 p-2.5">
          <p className="flex items-start gap-1.5 text-xs text-amber-200">
            <TriangleAlert size={13} className="mt-0.5 shrink-0" aria-hidden />
            <span>
              <strong className="font-medium">This AD group no longer exists.</strong> It was
              last seen {new Date(team.directory_missing_since).toLocaleString()} — renamed,
              moved, or deleted in the directory. The team's members are kept and the sync
              won't remove anyone, but membership stays read-only while the link is in place.
              Unlink to manage these people here, or restore the group in AD.
            </span>
          </p>
          <Button
            variant="ghost"
            className="mt-1.5 text-amber-200"
            onClick={() =>
              patchTeam.mutate({ directory_group_dn: null, directory_group_name: null })
            }
            disabled={patchTeam.isPending}
          >
            <Unlink size={13} aria-hidden />
            {patchTeam.isPending ? "Unlinking…" : "Unlink and edit here"}
          </Button>
        </div>
      )}
      {team.directory_group_dn ? (
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span
            className="rounded border border-sky-500/50 px-1.5 py-px text-[11px] text-sky-300"
            title={team.directory_group_dn}
          >
            {team.directory_group_name ?? team.directory_group_dn}
          </span>
          <span className="text-xs text-fg-muted">
            AD owns this team's members (nested groups count) — they can't be edited here.
            Unlinking keeps everyone and re-opens editing.
          </span>
          {directoryReady && (
            <Button variant="ghost" onClick={() => syncNow.mutate()} disabled={syncNow.isPending}>
              <FolderSync size={13} aria-hidden />
              {syncNow.isPending ? "Syncing…" : "Sync now"}
            </Button>
          )}
          <button
            type="button"
            onClick={() =>
              patchTeam.mutate({ directory_group_dn: null, directory_group_name: null })
            }
            disabled={patchTeam.isPending}
            aria-label={`Unlink ${team.name} from its directory group`}
            className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-50"
          >
            <X size={13} />
          </button>
        </div>
      ) : picking ? (
        <div className="flex max-w-md flex-col gap-2">
          <TextField
            label="Search AD groups"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Group name (cn)…"
          />
          {groups.isError ? (
            <p className="text-xs text-red-400">{errorMessage(groups.error)}</p>
          ) : groups.isPending ? (
            <p className="text-xs text-fg-muted">Searching…</p>
          ) : (groups.data ?? []).length === 0 ? (
            <p className="text-xs text-fg-muted">No directory groups match.</p>
          ) : (
            <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
              {(groups.data ?? []).map((group) => (
                <li key={group.dn}>
                  <button
                    type="button"
                    onClick={() =>
                      patchTeam.mutate({
                        directory_group_dn: group.dn,
                        directory_group_name: group.cn,
                      })
                    }
                    disabled={patchTeam.isPending}
                    className="flex w-full items-center gap-2 rounded-md border border-subtle px-2.5 py-1.5 text-left text-[13px] hover:bg-surface/60 cursor-pointer disabled:opacity-50"
                  >
                    <span className="truncate text-fg">{group.cn}</span>
                    <span className="ml-auto shrink-0 text-xs text-fg-muted">
                      {group.member_count} direct
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
          <Link2 size={13} aria-hidden />
          Link to an AD group
        </Button>
      )}
      {(patchTeam.isError || syncNow.isError) && (
        <p className="mt-1 text-xs text-red-400">
          {errorMessage(patchTeam.error ?? syncNow.error)}
        </p>
      )}
    </section>
  );
}
