import { PermissionScope, type PermissionInfo, type PermissionValue } from "../../lib/types";

interface PermissionMatrixProps {
  /** GET /permissions catalog rows. */
  catalog: PermissionInfo[];
  selected: readonly PermissionValue[];
  /** Omit to render read-only (builtin roles are immutable). */
  onToggle?: (permission: PermissionValue) => void;
}

const SCOPE_LABELS = {
  [PermissionScope.project]: "Project permissions",
  [PermissionScope.space]: "Space permissions",
  [PermissionScope.global]: "Global permissions",
  [PermissionScope.instance]: "Instance permissions",
} as const;

/** Every scope the catalog can serve. A missing entry is invisible, not an
 *  error — line 44 filters by scope, so an unlisted one matches nothing and
 *  its atoms never render (RADD-808). Keep in step with `PermissionScope`. */
const SCOPE_ORDER = [
  PermissionScope.project,
  PermissionScope.space,
  PermissionScope.global,
  PermissionScope.instance,
] as const;

/** Group a scope's rows by resource, preserving catalog (enum) order within each. */
function byResource(rows: PermissionInfo[]): [string, PermissionInfo[]][] {
  const groups = new Map<string, PermissionInfo[]>();
  for (const row of rows) {
    const list = groups.get(row.resource);
    if (list) list.push(row);
    else groups.set(row.resource, [row]);
  }
  return [...groups.entries()];
}

/**
 * Permission checkbox matrix for the roles admin UI (spec 09/50), grouped by
 * scope and then by resource so the full CRUD atom set stays scannable. The
 * action verb (create/update/delete/…) leads each row; read-only when
 * `onToggle` is absent (builtin roles are immutable).
 */
export function PermissionMatrix({ catalog, selected, onToggle }: PermissionMatrixProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {SCOPE_ORDER.map((scope) => {
        const rows = catalog.filter((permission) => permission.scope === scope);
        if (rows.length === 0) return null;
        return (
          <fieldset key={scope} className="rounded-lg border border-subtle p-3">
            <legend className="px-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
              {SCOPE_LABELS[scope]}
            </legend>
            <div className="flex flex-col gap-3">
              {byResource(rows).map(([resource, group]) => (
                <div key={resource}>
                  <p className="mb-1 font-mono text-[11px] uppercase tracking-wide text-fg-muted">
                    {resource}
                  </p>
                  <ul className="flex flex-col gap-1.5 border-l border-subtle pl-2.5">
                    {group.map((permission) => (
                      <li key={permission.key}>
                        <label
                          className={
                            "flex items-start gap-2 " +
                            (onToggle ? "cursor-pointer" : "cursor-default opacity-80")
                          }
                        >
                          <input
                            type="checkbox"
                            checked={selected.includes(permission.key)}
                            disabled={!onToggle}
                            onChange={() => onToggle?.(permission.key)}
                            className="mt-0.5 size-4 shrink-0 accent-accent"
                          />
                          <span className="min-w-0">
                            <span className="block text-xs font-medium text-fg">
                              {permission.action}
                            </span>
                            <span className="block text-xs text-fg-muted">
                              {permission.description}
                            </span>
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
