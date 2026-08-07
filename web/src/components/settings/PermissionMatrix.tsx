import {
  RELATION_ANY,
  heldRelations,
  type PermissionInfo,
  type PermissionValue,
} from "../../lib/types";

interface PermissionMatrixProps {
  /** GET /permissions catalog rows. */
  catalog: PermissionInfo[];
  selected: readonly PermissionValue[];
  /** Omit to render read-only (builtin roles are immutable). */
  onChange?: (permission: PermissionValue, relations: string[]) => void;
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
 * "what may they do to issues" is the question an admin is asking.
 *
 * Two axes hang off an atom, drawn differently on purpose:
 *
 * - **Scope** (project / global / space) is METADATA — a chip, not a control.
 *   The atom is a capability and WHERE it applies is a property of the GRANT
 *   (RADD-814): the role says what, the grant says where.
 * - **Relation** (`@own`, `@team`, `@assigned`, `@participant`) is the ATOM's
 *   own axis (RADD-823), so it is the role's business and gets controls.
 *
 * Before RADD-939 the second had no representation at all: the catalog carried
 * no qualifiers and this matched by exact string, so every qualified atom drew
 * as an unchecked box. The Baseline reported 11 permissions above a grid that
 * could express 4, and a qualified atom could be added only through the API and
 * removed not at all.
 *
 * Relations are a SET per atom, matching the server (`relations_held` returns a
 * frozenset; the gate passes if ANY held relation contains the one checked).
 * The Baseline needs it: `item.read@own` + `item.read@participant` is "items
 * they reported, or were shared into".
 *
 * Every catalog atom renders unconditionally — grouping never filters, so the
 * RADD-808 class (a scope value with no bucket silently dropping its atoms)
 * cannot recur here.
 */
export function PermissionMatrix({ catalog, selected, onChange }: PermissionMatrixProps) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {byResource(catalog).map(([resource, group]) => (
        <fieldset key={resource} className="rounded-lg border border-subtle p-3">
          <legend className="px-1 font-mono text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
            {resource.replace(/_/g, " ")}
          </legend>
          <ul className="flex flex-col gap-1.5">
            {group.map((permission) => (
              <PermissionRow
                key={permission.key}
                permission={permission}
                held={heldRelations(selected, permission.key)}
                onChange={onChange}
              />
            ))}
          </ul>
        </fieldset>
      ))}
    </div>
  );
}

const chipClasses = (on: boolean, editable: boolean) =>
  "rounded border px-1.5 py-px text-[10px] " +
  (editable ? "cursor-pointer " : "cursor-default ") +
  (on
    ? "border-accent/50 bg-accent/15 text-accent-text"
    : "border-subtle text-fg-muted hover:border-emphasis");

function PermissionRow({
  permission,
  held,
  onChange,
}: {
  permission: PermissionInfo;
  held: string[];
  onChange?: (permission: PermissionValue, relations: string[]) => void;
}) {
  const isHeld = held.length > 0;
  const options = permission.relations ?? [];
  const editable = Boolean(onChange);

  /** Toggle one qualifier. `any` is exclusive — it subsumes the rest. */
  const toggleRelation = (relation: string) => {
    if (!onChange) return;
    if (relation === RELATION_ANY) {
      onChange(permission.key, held.includes(RELATION_ANY) ? [] : [RELATION_ANY]);
      return;
    }
    const next = held.filter((entry) => entry !== RELATION_ANY);
    onChange(
      permission.key,
      next.includes(relation) ? next.filter((entry) => entry !== relation) : [...next, relation],
    );
  };

  return (
    <li>
      <label
        className={
          "flex items-start gap-2 " + (editable ? "cursor-pointer" : "cursor-default opacity-80")
        }
      >
        <input
          type="checkbox"
          checked={isHeld}
          disabled={!editable}
          // Checking lands on the WIDEST form; narrowing is a second, deliberate
          // click below. A box that silently granted "own only" would be a
          // different permission from the one its label names.
          onChange={() => onChange?.(permission.key, isHeld ? [] : [RELATION_ANY])}
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
          <span className="block text-xs text-fg-muted">{permission.description}</span>
        </span>
      </label>
      {/* Only once held: an unheld atom's qualifiers are not a question anyone
          is asking, and drawing them would treble the height of the grid. */}
      {isHeld && options.length > 0 && (
        <div className="ml-6 mt-1 flex flex-wrap items-center gap-1">
          <button
            type="button"
            aria-pressed={held.includes(RELATION_ANY)}
            disabled={!editable}
            onClick={() => toggleRelation(RELATION_ANY)}
            title={`Every ${permission.resource}, with no restriction`}
            className={chipClasses(held.includes(RELATION_ANY), editable)}
          >
            any
          </button>
          {options.map((option) => (
            <button
              key={option.key}
              type="button"
              aria-pressed={held.includes(option.key)}
              disabled={!editable}
              onClick={() => toggleRelation(option.key)}
              title={`Only ${permission.resource}s ${option.label}`}
              className={chipClasses(held.includes(option.key), editable)}
            >
              {option.key}
            </button>
          ))}
        </div>
      )}
    </li>
  );
}
