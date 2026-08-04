import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, UsersRound } from "lucide-react";
import { QueryError } from "../../components/QueryError";
import { groupsQuery } from "../../lib/queries";

/**
 * Settings → Groups (RADD-833): the directory-mirrored list — name, dn,
 * TRANSITIVE member count (the number a grant resolves to; direct counts
 * under-sell nested groups), nesting, and sync health. Deliberately
 * read-only: membership comes from AD, and this screen must not imply
 * otherwise. A group that stopped resolving is FLAGGED, never removed —
 * an AD outage must not become a permission outage (spec 87, moved here).
 */
export function GroupsSettingsPage() {
  const groups = useQuery(groupsQuery());

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-6">
      <div>
        <h2 className="flex items-center gap-2 text-base font-semibold text-heading">
          <UsersRound size={16} aria-hidden />
          Directory groups
        </h2>
        <p className="mt-1 text-xs text-fg-muted">
          Mirrored from the directory by the sync — membership and nesting are AD's,
          read-only here. Grants to a group reach every transitive member; the count
          below is that number, nesting included.
        </p>
      </div>

      <QueryError label="groups" error={groups.error} />

      {(groups.data ?? []).length === 0 ? (
        <p className="rounded-md border border-subtle p-4 text-xs text-fg-muted">
          No groups mirrored yet — import one from Settings → Directory, or wait for
          the periodic sync.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-subtle">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-subtle text-[11px] uppercase tracking-wide text-fg-faint">
                <th className="px-3 py-2">Group</th>
                <th className="px-3 py-2">Resolves to</th>
                <th className="px-3 py-2">Contained in</th>
                <th className="px-3 py-2">Contains</th>
                <th className="px-3 py-2">Health</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle/60">
              {(groups.data ?? []).map((group) => (
                <tr key={group.id}>
                  <td className="px-3 py-2">
                    <div className="text-fg">{group.name}</div>
                    <div className="font-mono text-[10px] text-fg-faint">{group.dn}</div>
                  </td>
                  <td className="px-3 py-2 text-fg">
                    {group.transitive_member_count ?? group.direct_member_count}
                    <span className="ml-1 text-fg-faint">
                      ({group.direct_member_count} direct)
                    </span>
                  </td>
                  <td className="px-3 py-2 text-fg-secondary">
                    {(group.parent_names ?? []).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2 text-fg-secondary">
                    {(group.child_names ?? []).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2">
                    {group.directory_missing_since ? (
                      <span
                        className="inline-flex items-center gap-1 rounded border border-amber-500/40 px-1.5 py-px text-[11px] text-amber-400"
                        title={`Stopped resolving in the directory ${new Date(group.directory_missing_since).toLocaleString()} — grants kept, removals held.`}
                      >
                        <AlertTriangle size={11} aria-hidden />
                        missing in AD
                      </span>
                    ) : (
                      <span className="text-[11px] text-fg-faint">OK</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
