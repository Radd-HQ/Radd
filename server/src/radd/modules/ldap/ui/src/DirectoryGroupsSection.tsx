import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, UsersRound } from "lucide-react";
import { Button, Chip, EmptyState, Pager, QueryError, Table, TableSkeleton, TBody, Td, TextField, Th, THead,
  useDebounced } from "@radd/plugin-sdk";
import { AddGroupToTeamDialog } from "./AddGroupToTeamDialog";
import { ImportGroupsDialog } from "./ImportGroupsDialog";
import { directoryGroupsQuery, mirroredGroupsQuery } from "./queries";
import { SEARCH_DEBOUNCE_MS, type DirectoryGroup } from "./types";

/** RADD-1294: a real AD returned ~4,400 groups and every one rendered its own checkbox. */
const GROUPS_PAGE_SIZE = 50;

/**
 * The live group browse (spec 85 §3 → RADD-829): every AD group under the configured base with
 * its MIRROR state (a `groups` row exists for the DN), per-row Import / Add-to-team, and bulk
 * import. Importing mirrors the group and ensures a same-named team holds it; "Add to team" puts an
 * already-mirrored group on any team. Un-mirroring doesn't exist — a group row is the directory's
 * truth, and removing it from a team is the team panel's job.
 */
export function DirectoryGroupsSection({ directoryReady }: { directoryReady: boolean }) {
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const groups = useQuery({ ...directoryGroupsQuery(debounced), enabled: directoryReady });
  const mirrored = useQuery({ ...mirroredGroupsQuery, enabled: directoryReady });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState<DirectoryGroup[] | null>(null);
  const [adding, setAdding] = useState<{ cn: string; groupId: string } | null>(null);
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [debounced]);

  const mirroredByDn = new Map((mirrored.data ?? []).map((group) => [group.dn, group]));
  const all = groups.data ?? [];
  const selectedGroups = all.filter((group) => selected.has(group.dn));
  const pageCount = Math.max(1, Math.ceil(all.length / GROUPS_PAGE_SIZE));
  const list = all.slice((page - 1) * GROUPS_PAGE_SIZE, page * GROUPS_PAGE_SIZE);
  const toggle = (dn: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(dn)) next.delete(dn);
      else next.add(dn);
      return next;
    });

  if (!directoryReady) {
    return <p className="text-xs text-fg-muted">Set the bind account on the Connection tab to browse directory groups.</p>;
  }

  return (
    <div className="flex flex-col gap-3" data-directory-groups>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          <TextField label="Search groups" value={q} onChange={(event) => setQ(event.target.value)}
            placeholder="Group name (cn)…" hint="Searches under the group base DN above." />
        </div>
        <Button variant="ghost" onClick={() => setImporting(selectedGroups)} disabled={selectedGroups.length === 0}>
          <Download size={14} aria-hidden />
          Import selected{selectedGroups.length > 0 ? ` (${selectedGroups.length})` : ""}
        </Button>
      </div>
      {groups.isPending ? (
        <TableSkeleton rows={4} />
      ) : groups.isError ? (
        <QueryError label="directory groups" error={groups.error} />
      ) : all.length === 0 ? (
        <EmptyState icon={UsersRound} message="No directory groups match." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr><Th /><Th>Group</Th><Th>Direct members</Th><Th>Mirrored</Th><Th /></tr>
            </THead>
            <TBody>
              {list.map((group) => {
                const mirror = mirroredByDn.get(group.dn);
                return (
                  <tr key={group.dn} data-directory-group={group.cn}>
                    <Td>
                      <input type="checkbox" checked={selected.has(group.dn)} onChange={() => toggle(group.dn)}
                        aria-label={`Select ${group.cn}`} className="accent-accent" />
                    </Td>
                    <Td>
                      <span className="block text-heading">{group.cn}</span>
                      <span className="block max-w-96 truncate text-xs text-fg-muted">{group.description || group.dn}</span>
                    </Td>
                    <Td>{group.member_count}</Td>
                    <Td>{mirror ? <span title={`Synced as ${mirror.name}`}><Chip>yes</Chip></span> : <span className="text-fg-faint">—</span>}</Td>
                    <Td className="whitespace-nowrap">
                      <span className="flex gap-1.5">
                        <Button size="sm" variant="secondary" onClick={() => setImporting([group])}>
                          {mirror ? "Re-import" : "Import as team"}
                        </Button>
                        {mirror && (
                          <Button size="sm" variant="secondary" onClick={() => setAdding({ cn: group.cn, groupId: mirror.id })}>
                            Add to team
                          </Button>
                        )}
                      </span>
                    </Td>
                  </tr>
                );
              })}
            </TBody>
          </Table>
        </div>
      )}
      {all.length > GROUPS_PAGE_SIZE && (
        <div data-groups-pager>
          <Pager page={page} pageCount={pageCount} total={all.length} onPage={setPage} noun="groups" compact />
        </div>
      )}
      {importing && (
        <ImportGroupsDialog preselected={importing} onClose={() => {
          setImporting(null);
          setSelected(new Set());
        }} />
      )}
      {adding && <AddGroupToTeamDialog cn={adding.cn} groupId={adding.groupId} onClose={() => setAdding(null)} />}
    </div>
  );
}
