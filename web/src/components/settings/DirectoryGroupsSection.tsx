import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, UsersRound } from "lucide-react";
import { api } from "../../lib/api";
import { SEARCH_DEBOUNCE_MS, apiTeamGroupsPath } from "../../lib/constants";
import { useDebounced } from "../../lib/hooks";
import { groupsQuery, ldapGroupsQuery, teamsQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import type { DirectoryGroup, TeamGroup } from "../../lib/types";
import { Button } from "../Button";
import { EmptyState } from "../EmptyState";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { SelectField } from "../SelectField";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { ImportGroupsDialog } from "./DirectoryImportDialogs";
import { settingsTableClasses } from "./SettingsPage";
import { ErrorText } from "../ErrorText";

const rowActionClasses =
  "rounded border border-strong px-2 py-0.5 text-[11px] text-fg-secondary cursor-pointer " +
  "disabled:opacity-50 hover:border-accent/50 hover:text-accent-text";

/**
 * The Directory page's Groups card (spec 85 §3 → RADD-829): every AD group
 * under the configured base with its MIRROR state (a `groups` row exists for
 * the DN), per-row Import / Add-to-team, and bulk import. Importing mirrors
 * the group and ensures a same-named team holds it; "Add to team" puts an
 * already-mirrored group on any team. Un-mirroring doesn't exist — a group
 * row is the directory's truth, and removing it from a team is the team
 * panel's job.
 */
export function DirectoryGroupsSection({ directoryReady }: { directoryReady: boolean }) {
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const groups = useQuery({ ...ldapGroupsQuery(debounced), enabled: directoryReady });
  const mirrored = useQuery({ ...groupsQuery(), enabled: directoryReady });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState<DirectoryGroup[] | null>(null);
  const [adding, setAdding] = useState<{ dn: string; cn: string; groupId: string } | null>(null);

  const mirroredByDn = new Map((mirrored.data ?? []).map((group) => [group.dn, group]));

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
                <th className={settingsTableClasses.head}>Mirrored</th>
                <th className={settingsTableClasses.head} />
              </tr>
            </thead>
            <tbody>
              {list.map((group) => {
                const mirror = mirroredByDn.get(group.dn);
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
                      {mirror ? (
                        <span
                          className="rounded border border-sky-500/50 px-1.5 py-px text-[11px] text-sky-300"
                          title={`Synced as ${mirror.name}`}
                        >
                          yes
                        </span>
                      ) : (
                        <span className="text-fg-faint">—</span>
                      )}
                    </td>
                    <td className={`${settingsTableClasses.cell} whitespace-nowrap`}>
                      <span className="flex gap-1.5">
                        <button
                          type="button"
                          onClick={() => setImporting([group])}
                          className={rowActionClasses}
                        >
                          {mirror ? "Re-import" : "Import as team"}
                        </button>
                        {mirror && (
                          <button
                            type="button"
                            onClick={() =>
                              setAdding({ dn: group.dn, cn: group.cn, groupId: mirror.id })
                            }
                            className={rowActionClasses}
                          >
                            Add to team
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {importing && (
        <ImportGroupsDialog
          preselected={importing}
          onClose={() => {
            setImporting(null);
            setSelected(new Set());
          }}
        />
      )}
      {adding && (
        <AddGroupToTeamDialog
          cn={adding.cn}
          groupId={adding.groupId}
          onClose={() => setAdding(null)}
        />
      )}
    </div>
  );
}

/** RADD-829: put an already-mirrored group on an EXISTING team as a member. */
function AddGroupToTeamDialog({
  cn,
  groupId,
  onClose,
}: {
  cn: string;
  groupId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const teams = useQuery(teamsQuery());
  const [teamId, setTeamId] = useState("");

  const add = useMutation({
    mutationFn: () => api.post<TeamGroup>(apiTeamGroupsPath(teamId), { group_id: groupId }),
    onSuccess: async () => {
      pushToast(`Added ${cn} to the team`, ToastKind.success);
      await queryClient.invalidateQueries({ queryKey: ["teams"] });
      onClose();
    },
  });

  return (
    <Modal title={`Add ${cn} to a team`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-fg-muted">
          The group's people (nested groups included) will count as members of the team;
          the directory sync keeps them current.
        </p>
        <SelectField
          label="Team"
          value={teamId}
          onChange={(event) => setTeamId(event.target.value)}
        >
          <option value="">Pick a team…</option>
          {(teams.data ?? []).map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </SelectField>
        {add.isError && <ErrorText error={add.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => add.mutate()} disabled={!teamId || add.isPending}>
            {add.isPending ? "Adding…" : "Add group"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
