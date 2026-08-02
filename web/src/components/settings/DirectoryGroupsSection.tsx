import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Link2, UsersRound } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { SEARCH_DEBOUNCE_MS, apiTeamPath } from "../../lib/constants";
import { useDebounced } from "../../lib/hooks";
import { ldapGroupsQuery, teamsQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import type { DirectoryGroup, Team, TeamUpdate } from "../../lib/types";
import { Button } from "../Button";
import { EmptyState } from "../EmptyState";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { SelectField } from "../SelectField";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { ImportGroupsDialog } from "./DirectoryImportDialogs";
import { settingsTableClasses } from "./SettingsPage";

const rowActionClasses =
  "rounded border border-strong px-2 py-0.5 text-[11px] text-fg-secondary cursor-pointer " +
  "disabled:opacity-50 hover:border-accent/50 hover:text-accent-text";

/**
 * The Directory page's Groups card (spec 85 §3): every group under the
 * configured base with its LINK STATE (the team already holding that DN), a
 * per-row Import-as-team / Link-to-existing-team / Unlink, and bulk import.
 * Import reuses the spec-84 dialog (preselected mode); link/unlink ride the
 * ordinary team PATCH.
 */
export function DirectoryGroupsSection({ directoryReady }: { directoryReady: boolean }) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const groups = useQuery({ ...ldapGroupsQuery(debounced), enabled: directoryReady });
  const teams = useQuery({ ...teamsQuery(), enabled: directoryReady });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState<DirectoryGroup[] | null>(null);
  const [linking, setLinking] = useState<DirectoryGroup | null>(null);

  const linkedByDn = new Map(
    (teams.data ?? [])
      .filter((team) => team.directory_group_dn)
      .map((team) => [team.directory_group_dn as string, team]),
  );

  const unlink = useMutation({
    mutationFn: (team: Team) =>
      api.patch<Team>(apiTeamPath(team.id), {
        directory_group_dn: null,
        directory_group_name: null,
      } satisfies TeamUpdate),
    onSuccess: async (team) => {
      pushToast(`Unlinked ${team.name} from its directory group`, ToastKind.success);
      await queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
  });

  const toggle = (dn: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(dn)) next.delete(dn);
      else next.add(dn);
      return next;
    });
  };

  const list = groups.data ?? [];
  const selectedGroups = list.filter((group) => selected.has(group.dn));

  if (!directoryReady) {
    return (
      <p className="text-xs text-fg-muted">
        Configure the bind account (RADD_LDAP_BIND_DN / _PASSWORD) to browse directory groups.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          <TextField
            label="Search groups"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Group name (cn)…"
            hint="Searches under the group base DN above."
          />
        </div>
        <Button
          variant="ghost"
          onClick={() => setImporting(selectedGroups)}
          disabled={selectedGroups.length === 0}
        >
          <Download size={14} aria-hidden />
          Import selected{selectedGroups.length > 0 ? ` (${selectedGroups.length})` : ""}
        </Button>
      </div>
      {groups.isPending ? (
        <TableSkeleton rows={4} />
      ) : groups.isError ? (
        <QueryError label="directory groups" error={groups.error} />
      ) : list.length === 0 ? (
        <EmptyState icon={UsersRound} message="No directory groups match." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <table className={settingsTableClasses.table}>
            <thead>
              <tr>
                <th className={settingsTableClasses.head} />
                <th className={settingsTableClasses.head}>Group</th>
                <th className={settingsTableClasses.head}>Direct members</th>
                <th className={settingsTableClasses.head}>Linked team</th>
                <th className={settingsTableClasses.head} />
              </tr>
            </thead>
            <tbody>
              {list.map((group) => {
                const linked = linkedByDn.get(group.dn);
                return (
                  <tr key={group.dn} className="last:[&>td]:border-b-0">
                    <td className={settingsTableClasses.cell}>
                      <input
                        type="checkbox"
                        checked={selected.has(group.dn)}
                        onChange={() => toggle(group.dn)}
                        aria-label={`Select ${group.cn}`}
                        className="accent-accent"
                      />
                    </td>
                    <td className={settingsTableClasses.cell}>
                      <span className="block text-heading">{group.cn}</span>
                      <span className="block max-w-96 truncate text-xs text-fg-muted">
                        {group.description || group.dn}
                      </span>
                    </td>
                    <td className={settingsTableClasses.cell}>{group.member_count}</td>
                    <td className={settingsTableClasses.cell}>
                      {linked ? (
                        <span
                          className="rounded border border-sky-500/50 px-1.5 py-px text-[11px] text-sky-300"
                          title={group.dn}
                        >
                          {linked.name}
                        </span>
                      ) : (
                        <span className="text-fg-faint">—</span>
                      )}
                    </td>
                    <td className={`${settingsTableClasses.cell} whitespace-nowrap`}>
                      {linked ? (
                        <button
                          type="button"
                          onClick={() => unlink.mutate(linked)}
                          disabled={unlink.isPending}
                          className={rowActionClasses}
                        >
                          Unlink
                        </button>
                      ) : (
                        <span className="flex gap-1.5">
                          <button
                            type="button"
                            onClick={() => setImporting([group])}
                            className={rowActionClasses}
                          >
                            Import as team
                          </button>
                          <button
                            type="button"
                            onClick={() => setLinking(group)}
                            className={rowActionClasses}
                          >
                            Link to existing team
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {unlink.isError && <p className="text-xs text-red-400">{errorMessage(unlink.error)}</p>}
      {importing && (
        <ImportGroupsDialog
          preselected={importing}
          onClose={() => {
            setImporting(null);
            setSelected(new Set());
          }}
        />
      )}
      {linking && <LinkTeamDialog group={linking} onClose={() => setLinking(null)} />}
    </div>
  );
}

/** Spec 85 §3: link one discovered group to an EXISTING team — team pick
 * (already-linked teams excluded) → the ordinary team PATCH. */
function LinkTeamDialog({ group, onClose }: { group: DirectoryGroup; onClose: () => void }) {
  const queryClient = useQueryClient();
  const teams = useQuery(teamsQuery());
  const [teamId, setTeamId] = useState("");
  const candidates = (teams.data ?? []).filter((team) => !team.directory_group_dn);

  const link = useMutation({
    mutationFn: () =>
      api.patch<Team>(apiTeamPath(teamId), {
        directory_group_dn: group.dn,
        directory_group_name: group.cn,
      } satisfies TeamUpdate),
    onSuccess: async (team) => {
      pushToast(`Linked ${group.cn} to ${team.name}`, ToastKind.success);
      await queryClient.invalidateQueries({ queryKey: ["teams"] });
      await queryClient.invalidateQueries({ queryKey: ["teamMembers"] });
      onClose();
    },
  });

  return (
    <Modal title={`Link ${group.cn} to a team`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-fg-muted">
          The team's membership will sync from the directory group (nested groups count);
          hand-added members are kept.
        </p>
        <SelectField
          label="Team"
          value={teamId}
          onChange={(event) => setTeamId(event.target.value)}
        >
          <option value="">Choose a team…</option>
          {candidates.map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </SelectField>
        {teams.data && candidates.length === 0 && (
          <p className="text-xs text-fg-muted">
            Every team is already linked — unlink one first, or import the group as a
            new team.
          </p>
        )}
        {link.isError && <p className="text-xs text-red-400">{errorMessage(link.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => link.mutate()} disabled={!teamId || link.isPending}>
            <Link2 size={14} aria-hidden />
            {link.isPending ? "Linking…" : "Link"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
