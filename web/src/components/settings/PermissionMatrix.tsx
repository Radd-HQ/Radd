import { type PermissionInfo, type PermissionValue } from "../../lib/types";

interface PermissionMatrixProps {
  /** GET /permissions catalog rows. */
  catalog: PermissionInfo[];
  selected: readonly PermissionValue[];
  /** Omit to render read-only (builtin roles are immutable). */
  onToggle?: (permission: PermissionValue) => void;
}

/** Group the whole catalog by resource, preserving catalog (enum) order. */
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
 * RESOURCE (RADD-815): one block per resource listing its verbs, because
 * "what may they do to issues" is the question an admin is asking. The scope
 * an atom is checked at is METADATA on the row — a chip, not a box around it —
 * since the atom is a capability and WHERE it applies is a property of the
 * grant (RADD-814): the role says what, the grant says where.
 *
 * Every catalog atom renders unconditionally — grouping never filters, so the
 * RADD-808 class (a scope value with no bucket silently dropping its atoms)
 * cannot recur here.
 */
export function PermissionMatrix({ catalog, selected, onToggle }: PermissionMatrixProps) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {byResource(catalog).map(([resource, group]) => (
        <fieldset key={resource} className="rounded-lg border border-subtle p-3">
          <legend className="px-1 font-mono text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
            {resource.replace(/_/g, " ")}
          </legend>
          <ul className="flex flex-col gap-1.5">
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
                    <span className="flex items-center gap-1.5 text-xs font-medium text-fg">
                      {permission.action}
                      <span
                        className="rounded border border-subtle px-1 text-[9px] uppercase text-fg-faint"
                        title={`Checked at ${permission.scope} scope — WHERE it applies is chosen on the grant.`}
                      >
                        {permission.scope}
                      </span>
                    </span>
                    <span className="block text-xs text-fg-muted">
                      {permission.description}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      ))}
    </div>
  );
}
