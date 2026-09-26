import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { formatDateTime, IconButton, ListSearchInput, QueryError, RoleGrants, Table, TBody, Td, Th, THead,
  useListFilter, usePermissions } from "@radd/plugin-sdk";
import { mirroredGroupsQuery } from "./queries";
import type { MirroredGroup } from "./types";

/** Groups Radd mirrors from the directory: transitive member count, nesting, missing-in-AD health,
 *  and each group's role grants. Membership is read-only — AD owns it. */
export function MirroredGroupsSection({ directoryReady }: { directoryReady: boolean }) {
  const canManage = usePermissions().global("role.update");
  const groups = useQuery({ ...mirroredGroupsQuery, enabled: directoryReady });
  const all = groups.data ?? [];
  const search = useListFilter(all, (group) => [group.name, group.dn]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (!directoryReady) return null;

  return (
    <div className="mt-4 flex flex-col gap-3" data-mirrored-groups>
      <div>
        <h3 className="text-[13px] font-semibold text-heading">Mirrored groups</h3>
        <p className="mt-0.5 text-xs text-fg-muted">
          Membership and nesting are the directory's, read-only here. A grant to a group reaches every{" "}
          <strong>transitive</strong> member — the count below is that number, nesting included.
        </p>
      </div>
      {groups.isError && <QueryError label="mirrored groups" error={groups.error} />}
      {all.length === 0 ? (
        <p className="rounded-md border border-subtle p-4 text-xs text-fg-muted">
          Nothing mirrored yet — import a group above, or wait for the periodic sync.
        </p>
      ) : (
        <>
          {all.length > 8 && (
            <ListSearchInput value={search.filter} onChange={search.setFilter}
              placeholder="Filter mirrored groups by name or DN…" total={all.length} matched={search.filtered.length} noun="groups" />
          )}
          {search.filtered.length === 0 ? (
            <p className="rounded-md border border-subtle p-4 text-xs text-fg-muted">
              No mirrored groups match “{search.filter.trim()}”.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-subtle">
              <Table>
                <THead>
                  <tr><Th /><Th>Group</Th><Th>Reaches</Th><Th>Contained in</Th><Th>Contains</Th><Th>Health</Th></tr>
                </THead>
                <TBody>
                  {search.filtered.map((group) => (
                    <MirroredRow key={group.id} group={group} canManage={canManage} expanded={expandedId === group.id}
                      onToggle={() => setExpandedId(expandedId === group.id ? null : group.id)} />
                  ))}
                </TBody>
              </Table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MirroredRow({ group, canManage, expanded, onToggle }: {
  group: MirroredGroup; canManage: boolean; expanded: boolean; onToggle: () => void;
}) {
  const missing = group.directory_missing_since;
  return (
    <Fragment>
      <tr data-mirrored-group={group.name}>
        <Td>
          <IconButton onClick={onToggle} aria-expanded={expanded}
            aria-label={`${expanded ? "Hide" : "Show"} roles granted to ${group.name}`}>
            {expanded ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
          </IconButton>
        </Td>
        <Td>
          <span className="block text-heading">{group.name}</span>
          <span className="block max-w-96 truncate font-mono text-[10px] text-fg-faint">{group.dn}</span>
        </Td>
        <Td>
          {group.transitive_member_count ?? group.direct_member_count}
          <span className="ml-1 text-fg-faint">({group.direct_member_count} direct)</span>
        </Td>
        <Td>{(group.parent_names ?? []).join(", ") || "—"}</Td>
        <Td>{(group.child_names ?? []).join(", ") || "—"}</Td>
        <Td>
          {missing ? (
            <span className="inline-flex items-center gap-1 rounded border border-status-warning/40 px-1.5 py-px text-[11px] text-status-warning-ink"
              title={`Missing since ${formatDateTime(missing)}. Memberships and access are retained until reviewed.`}>
              <AlertTriangle size={11} aria-hidden />
              missing in AD
            </span>
          ) : (
            <span className="text-[11px] text-fg-faint">OK</span>
          )}
        </Td>
      </tr>
      {expanded && (
        <tr data-mirrored-group-roles={group.name}>
          <Td />
          <Td colSpan={5}>
            {missing && (
              <p className="mb-3 text-xs text-status-warning-ink">
                Missing since {formatDateTime(missing)}. Existing members still receive this group’s access. Restore the
                original directory identity for a renamed group, or explicitly revoke its roles and remove its team links
                if it was deleted. Directory outages do not automatically remove access; review resource deny rules
                before removing membership.
              </p>
            )}
            <RoleGrants subject={{ groupId: group.id }} canManage={canManage} />
          </Td>
        </tr>
      )}
    </Fragment>
  );
}
