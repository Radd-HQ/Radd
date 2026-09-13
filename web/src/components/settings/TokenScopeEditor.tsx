import { useId, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { permissionsCatalogQuery, projectsQuery } from "../../lib/queries";
import type { PermissionValue, TokenScopes } from "../../lib/types";
import { TokenMultiSelect } from "../TokenMultiSelect";
import { ScopePicker } from "./ScopePicker";

/**
 * ONE editor for a key's spec-113 scope, shared by personal tokens and
 * service-account keys (RADD-1009). `null` is full authority — the default,
 * and what every key minted before this editor existed carries. "Restrict
 * this key" reveals the permission atoms and the project scope; the wire shape
 * is `{global: [atoms]}` for everywhere, `{projects: {id: [atoms]}}` per
 * project, and the server intersects it with the account (a key can never
 * exceed its account), which is why `allowedAtoms` is a courtesy filter, not
 * a gate.
 */
export function TokenScopeEditor({
  value,
  onChange,
  allowedAtoms = null,
  disabled = false,
}: {
  value: TokenScopes | null;
  onChange: (next: TokenScopes | null) => void;
  /** Which catalog atoms to OFFER — the owner's effective set for a personal
   *  key. `null` offers the whole catalog (a service account's roles are not
   *  known client-side; the server narrows to them regardless). */
  allowedAtoms?: ((atom: PermissionValue) => boolean) | null;
  disabled?: boolean;
}) {
  const id = useId();
  const catalog = useQuery(permissionsCatalogQuery);
  const projects = useQuery(projectsQuery());
  const restricted = value !== null;
  const { atoms, projectIds } = useMemo(() => scopeParts(value), [value]);

  const atomOptions = useMemo(
    () =>
      (catalog.data ?? [])
        .filter((entry) => allowedAtoms === null || allowedAtoms(entry.key))
        .map((entry) => ({ value: entry.key, label: entry.key, hint: entry.description, group: entry.scope }))
        .sort((a, b) => a.value.localeCompare(b.value)),
    [catalog.data, allowedAtoms],
  );

  const emit = (nextAtoms: string[], nextProjects: string[]) => onChange(composeScopes(nextAtoms, nextProjects));

  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-[13px] text-fg">
        <input
          id={`${id}-restrict`}
          type="checkbox"
          checked={restricted}
          disabled={disabled}
          onChange={(event) => (event.target.checked ? emit([], []) : onChange(null))}
          className="size-3.5 accent-accent disabled:opacity-50"
        />
        Restrict this key
      </label>
      <p className="pl-[22px] text-xs text-fg-muted">
        {restricted
          ? "Only the permissions chosen here — everywhere, or in the projects you pick. Never more than the account itself holds."
          : "Unrestricted: the key acts with everything the account can do, now and later."}
      </p>
      {restricted && (
        <div className="flex flex-col gap-2 pl-[22px]">
          <div>
            <span className="mb-1 block text-xs font-medium text-fg-secondary">Permissions</span>
            <TokenMultiSelect
              ariaLabel="Key permissions"
              value={atoms}
              onChange={(next) => emit(next, projectIds)}
              options={atomOptions}
              disabled={disabled}
              placeholder="item.read, item.create…"
            />
          </div>
          <div>
            <span className="mb-1 block text-xs font-medium text-fg-secondary">Projects</span>
            <ScopePicker
              value={projectIds}
              onChange={(next) => emit(atoms, next)}
              projects={projects.data ?? []}
              disabled={disabled}
              globalLabel="Everywhere"
            />
          </div>
        </div>
      )}
    </div>
  );
}

/** The atoms + project ids a stored scope expresses (project atoms unioned). */
export function scopeParts(value: TokenScopes | null): { atoms: string[]; projectIds: string[] } {
  if (value === null) return { atoms: [], projectIds: [] };
  const projectIds = Object.keys(value.projects ?? {});
  const atoms = projectIds.length
    ? [...new Set(projectIds.flatMap((id) => value.projects?.[id] ?? []))]
    : [...(value.global ?? [])];
  return { atoms, projectIds };
}

/** The wire shape for a restricted key: the same atoms in every chosen project,
 *  or globally when no project is chosen. */
export function composeScopes(atoms: string[], projectIds: string[]): TokenScopes {
  if (projectIds.length === 0) return { global: atoms };
  return { projects: Object.fromEntries(projectIds.map((id) => [id, atoms])) };
}

/** A restricted key with no atoms would be a key that can do nothing — refuse
 *  to mint it rather than let an unfinished form produce a dead credential. */
export function scopeIsIncomplete(value: TokenScopes | null): boolean {
  return value !== null && scopeParts(value).atoms.length === 0;
}

/** The compact read-back on a token row: what a stored scope amounts to. */
export function TokenScopeSummary({ scopes }: { scopes: TokenScopes | null | undefined }) {
  if (!scopes) return <span className="text-xs text-fg-muted">Full authority</span>;
  const { atoms, projectIds } = scopeParts(scopes);
  const where = projectIds.length === 0
    ? "everywhere"
    : `${projectIds.length} ${projectIds.length === 1 ? "project" : "projects"}`;
  return (
    <span className="text-xs text-fg-secondary" title={atoms.join(", ")}>
      {atoms.length} {atoms.length === 1 ? "permission" : "permissions"} · {where}
    </span>
  );
}
