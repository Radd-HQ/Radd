import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { formatDateTime } from "../../lib/dates";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { groupsQuery } from "../../lib/queries";
import { Permission } from "../../lib/types";
import { ListSearchInput } from "../ListSearchInput";
import { QueryError } from "../QueryError";
import { RoleGrantsSection } from "./RoleGrantsSection";
import { settingsTableClasses } from "./SettingsPage";

/**
 * The groups Radd has MIRRORED from the directory (RADD-833, moved here by
 * RADD-931 from its own Settings → Groups tab).
 *
 * That tab was a read-only table with no action on it, one click from the live
 * browse above — and the reason it looked inert was a missing feature, not a
 * missing button: role grants to a group have been fully implemented
 * server-side since RADD-832 (`auth/grants.py` ORs the caller's transitive
 * groups into the grant lookup) and no SPA surface ever passed a `group_id`.
 * Granting a role to an AD group was reachable only by hand-writing the POST.
 *
 * So the mirror table keeps what it uniquely knew — the TRANSITIVE member
 * count, nesting, and the missing-in-AD health chip — and each row expands to
 * the grant editor. Membership itself stays read-only: AD owns it, and this
 * screen must not imply otherwise.
 */
export function MirroredGroupsSection({ directoryReady }: { directoryReady: boolean }) {
  const perms = usePermissions();
  const groups = useQuery({ ...groupsQuery(), enabled: directoryReady });
  const all = groups.data ?? [];
  const search = useListFilter(all, (group) => [group.name, group.dn]);
  const list = search.filtered;
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (!directoryReady) return null;

  return (
    <div className="mt-4 flex flex-col gap-3">
      <div>
        <h3 className="text-[13px] font-semibold text-heading">Mirrored groups</h3>
        <p className="mt-0.5 text-xs text-fg-muted">
          Membership and nesting are the directory's, read-only here. A grant to a group
          reaches every <strong>transitive</strong> member — the count below is that number,
          nesting included.
        </p>
      </div>

      <QueryError label="mirrored groups" error={groups.error} />

      {all.length === 0 ? (
        <p className="rounded-md border border-subtle p-4 text-xs text-fg-muted">
          Nothing mirrored yet — import a group above, or wait for the periodic sync.
        </p>
      ) : (
        <>
          {all.length > 8 && (
            <ListSearchInput
              value={search.filter}
              onChange={search.setFilter}
              placeholder="Filter mirrored groups by name or DN…"
              total={all.length}
              matched={list.length}
              noun="groups"
            />
          )}
          {list.length === 0 ? (
            <p className="rounded-md border border-subtle p-4 text-xs text-fg-muted">
              No mirrored groups match “{search.filter.trim()}”.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-subtle">
              <table className={settingsTableClasses.table}>
                <thead>
                  <tr>
                    <th className={settingsTableClasses.head} />
                    <th className={settingsTableClasses.head}>Group</th>
                    <th className={settingsTableClasses.head}>Reaches</th>
                    <th className={settingsTableClasses.head}>Contained in</th>
                    <th className={settingsTableClasses.head}>Contains</th>
                    <th className={settingsTableClasses.head}>Health</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((group) => {
                    const expanded = expandedId === group.id;
                    return [
                      <tr key={group.id}>
                        <td className={settingsTableClasses.cell}>
                          <button
                            type="button"
                            onClick={() => setExpandedId(expanded ? null : group.id)}
                            aria-expanded={expanded}
                            aria-label={`${expanded ? "Hide" : "Show"} roles granted to ${group.name}`}
                            className="rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                          >
                            {expanded ? (
                              <ChevronDown size={14} aria-hidden />
                            ) : (
                              <ChevronRight size={14} aria-hidden />
                            )}
                          </button>
                        </td>
                        <td className={settingsTableClasses.cell}>
                          <span className="block text-heading">{group.name}</span>
                          <span className="block max-w-96 truncate font-mono text-[10px] text-fg-faint">
                            {group.dn}
                          </span>
                        </td>
                        <td className={settingsTableClasses.cell}>
                          {group.transitive_member_count ?? group.direct_member_count}
                          <span className="ml-1 text-fg-faint">
                            ({group.direct_member_count} direct)
                          </span>
                        </td>
                        <td className={settingsTableClasses.cell}>
                          {(group.parent_names ?? []).join(", ") || "—"}
                        </td>
                        <td className={settingsTableClasses.cell}>
                          {(group.child_names ?? []).join(", ") || "—"}
                        </td>
                        <td className={settingsTableClasses.cell}>
                          {group.directory_missing_since ? (
                            <span
                              className="inline-flex items-center gap-1 rounded border border-amber-500/40 px-1.5 py-px text-[11px] text-amber-400"
                              title={`Stopped resolving in the directory ${formatDateTime(group.directory_missing_since)} — grants kept, removals held. An AD outage must not become a permission outage.`}
                            >
                              <AlertTriangle size={11} aria-hidden />
                              missing in AD
                            </span>
                          ) : (
                            <span className="text-[11px] text-fg-faint">OK</span>
                          )}
                        </td>
                      </tr>,
                      expanded ? (
                        <tr key={`${group.id}-roles`}>
                          <td className={settingsTableClasses.cell} />
                          <td className={settingsTableClasses.cell} colSpan={5}>
                            <RoleGrantsSection
                              subject={{ groupId: group.id }}
                              canManage={perms.global(Permission.roleUpdate)}
                            />
                          </td>
                        </tr>
                      ) : null,
                    ];
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
