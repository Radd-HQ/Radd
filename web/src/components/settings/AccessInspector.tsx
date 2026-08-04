/**
 * The permission inspector (RADD-779 → RADD-809): both halves of the access
 * system explained from one place.
 *
 * `EffectivePermissions` — the ATOM half, now resolvable at instance / project
 * / SPACE scope, each row carrying its channel (membership, team, grant) and a
 * backlink to the supplying role. `ResourceAccessSection` — the spec-92 half:
 * which grant rows reach this person, through what, at what scope, plus the
 * default-open distinction ("readable because nothing restricts it" is a
 * different fact from "granted"). `TeamAccessSection` — the same treatment for
 * "what does membership of this team confer".
 *
 * Everything is resolved server-side; this file only renders. A second opinion
 * computed in the client would be the one that disagrees with the resolver.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { errorMessage } from "../../lib/api";
import { RoutePath } from "../../lib/constants";
import {
  pageSpacesQuery,
  projectsQuery,
  teamAccessQuery,
  userAccessQuery,
  userPermissionsQuery,
} from "../../lib/queries";
import type { PermissionSource, ResourceTypeAccess } from "../../lib/types";
import { SelectField } from "../SelectField";

const GLOBAL_SCOPE = "";
const PROJECT_PREFIX = "project:";
const SPACE_PREFIX = "space:";

/** The atom half, with a scope picker (instance-wide / one project / one space). */
export function EffectivePermissions({ userId }: { userId: string }) {
  const [scope, setScope] = useState(GLOBAL_SCOPE);
  const projects = useQuery(projectsQuery());
  const spaces = useQuery(pageSpacesQuery());
  const projectId = scope.startsWith(PROJECT_PREFIX) ? scope.slice(PROJECT_PREFIX.length) : undefined;
  const spaceId = scope.startsWith(SPACE_PREFIX) ? scope.slice(SPACE_PREFIX.length) : undefined;
  const { data, isPending, isError, error } = useQuery(
    userPermissionsQuery(userId, { projectId, spaceId }),
  );

  const picker = (
    <div className="flex items-baseline gap-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
        Effective permissions
      </p>
      <SelectField
        label=""
        ariaLabel="Resolution scope"
        className="w-52"
        value={scope}
        onChange={(event) => setScope(event.target.value)}
      >
        <option value={GLOBAL_SCOPE}>Instance-wide</option>
        {(projects.data ?? []).length > 0 && (
          <optgroup label="On a project">
            {(projects.data ?? []).map((project) => (
              <option key={project.id} value={`${PROJECT_PREFIX}${project.id}`}>
                {project.key} — {project.name}
              </option>
            ))}
          </optgroup>
        )}
        {(spaces.data ?? []).length > 0 && (
          <optgroup label="In a space">
            {(spaces.data ?? []).map((space) => (
              <option key={space.id} value={`${SPACE_PREFIX}${space.id}`}>
                {space.name}
              </option>
            ))}
          </optgroup>
        )}
      </SelectField>
    </div>
  );

  if (isPending)
    return (
      <div className="flex flex-col gap-2">
        {picker}
        <p className="text-xs text-fg-muted">Resolving permissions…</p>
      </div>
    );
  if (isError)
    return (
      <div className="flex flex-col gap-2">
        {picker}
        <p className="text-xs text-red-400">{errorMessage(error)}</p>
      </div>
    );

  const rows = data ?? [];
  const admin = rows.find((row) => row.kind === "instance-admin");
  if (admin) {
    return (
      <p className="rounded-md border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-fg-secondary">
        <strong className="text-heading">Everything.</strong> An instance administrator bypasses
        every permission check, so no role or grant applies — switch Administrator off to make
        the rules below take effect.
      </p>
    );
  }

  // Group by source (Baseline first, then each role) so the answer reads as
  // "Baseline gives them X, the Member role adds Y".
  const bySource = new Map<string, PermissionSource[]>();
  for (const row of rows) {
    const key = row.kind === "baseline" ? "Baseline" : (row.role_name ?? "Granted role");
    const list = bySource.get(key) ?? [];
    list.push(row);
    bySource.set(key, list);
  }

  return (
    <div className="flex flex-col gap-2">
      {picker}
      {rows.length === 0 ? (
        <p className="text-xs text-fg-muted">
          None — this account cannot do anything here until Baseline or a granted role gives it
          something.
        </p>
      ) : (
        [...bySource.entries()].map(([source, atoms]) => (
          <div key={source} className="flex flex-wrap items-baseline gap-1.5">
            <SourceLabel source={source} first={atoms[0]} />
            {atoms.map((atom) => (
              <span
                key={atom.permission}
                title={atomTitle(atom, source)}
                className={
                  "rounded border px-1 font-mono text-[10px] " +
                  (atom.implied ? "border-subtle text-fg-muted" : "border-strong text-fg-secondary")
                }
              >
                {atom.permission}
              </span>
            ))}
          </div>
        ))
      )}
      <p className="text-[10px] text-fg-faint">
        Dimmed atoms are implied by an umbrella (project.manage implies state.create), not
        ticked on the role itself. Hover an atom for how its role reached this scope.
      </p>
    </div>
  );
}

/** The source name, linked to the role that supplies it (RADD-809 backlinks). */
function SourceLabel({ source, first }: { source: string; first: PermissionSource | undefined }) {
  const label = (
    <span className="shrink-0 text-[11px] font-medium text-fg-secondary">
      {source}
      {first?.via === "team" && first.via_team ? (
        <span className="text-fg-faint"> via {first.via_team}</span>
      ) : null}
      {first && first.kind === "role" && first.scope !== "global" ? (
        <span className="text-fg-faint"> · {first.scope}-scoped</span>
      ) : null}
    </span>
  );
  if (!first?.role_id) return label;
  return (
    <Link
      to={RoutePath.settingsRoles}
      hash={first.role_id}
      className="shrink-0 hover:underline"
      title="Open this role in Settings → Roles"
    >
      {label}
    </Link>
  );
}

function atomTitle(atom: PermissionSource, source: string): string {
  const base = atom.implied
    ? `Implied by an umbrella permission, not ticked directly on ${source}.`
    : `Granted directly by ${source}.`;
  const via =
    atom.via === "membership"
      ? "Reached this project through a membership row."
      : atom.via === "team"
        ? `Carried by the ${atom.via_team ?? "?"} team's project attachment.`
        : atom.via === "grant"
          ? atom.scope === "global"
            ? "Granted instance-wide."
            : `Granted scoped to this ${atom.scope}.`
          : "";
  return via ? `${base} ${via}` : base;
}

/** The spec-92 half: resource grants reaching this person, plus the counts. */
export function ResourceAccessSection({ userId }: { userId: string }) {
  const { data, isPending, isError, error } = useQuery(userAccessQuery(userId));
  if (isPending) return <p className="text-xs text-fg-muted">Resolving resource access…</p>;
  if (isError) return <p className="text-xs text-red-400">{errorMessage(error)}</p>;
  const summary = data.summary;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
        Resource access
      </p>
      <p className="text-xs text-fg-secondary">
        Can read items in <strong>{summary.readable_projects}</strong> and edit in{" "}
        <strong>{summary.updatable_projects}</strong> of {summary.total_projects} projects
        {summary.readable_spaces != null && summary.total_spaces != null ? (
          <>
            {" "}
            · can read <strong>{summary.readable_spaces}</strong> of {summary.total_spaces} wiki
            spaces
          </>
        ) : null}
        .
      </p>
      <ResourceSections sections={data.resources} subject="they" />
    </div>
  );
}

/** Shared renderer: per-type grant rows + the default-open statement. */
export function ResourceSections({
  sections,
  subject,
}: {
  sections: ResourceTypeAccess[];
  subject: string;
}) {
  const withRows = sections.filter((section) => section.rows.length > 0);
  const openTypes = sections.filter((s) => s.default_open).map((s) => s.label.toLowerCase());
  return (
    <div className="flex flex-col gap-1.5">
      {withRows.length === 0 ? (
        <p className="text-xs text-fg-muted">No resource grants name {subject}.</p>
      ) : (
        withRows.map((section) => (
          <div key={section.resource_type} className="flex flex-col gap-0.5">
            <p className="text-[11px] font-medium text-fg-secondary">{section.label}s</p>
            <ul className="flex flex-col gap-0.5">
              {section.rows.map((row, index) => (
                <li key={index} className="text-xs text-fg">
                  <span className="text-heading">
                    {row.resource_label ?? row.resource_id}
                  </span>{" "}
                  — {row.access}
                  {row.effect === "deny" && (
                    <span className="ml-1 rounded border border-red-500/40 px-1 text-[10px] uppercase text-red-400">
                      deny
                    </span>
                  )}
                  <span className="text-fg-muted">
                    {row.subject_name
                      ? ` via ${row.subject_type} ${row.subject_name}`
                      : " granted directly"}
                    {row.project_key ? ` · on ${row.project_key}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
      {openTypes.length > 0 && (
        <p className="text-[10px] text-fg-faint">
          Default-open kinds ({openTypes.join(", ")}) are reachable with no grant at all —
          "readable because nothing restricts it" is different from "granted", and only the
          restricted ones need rows here.
        </p>
      )}
    </div>
  );
}

/** What membership of this team confers (RADD-809) — the team owner's question. */
export function TeamAccessSection({ teamId }: { teamId: string }) {
  const { data, isPending, isError, error } = useQuery(teamAccessQuery(teamId));
  if (isPending) return <p className="text-xs text-fg-muted">Resolving team access…</p>;
  if (isError) return <p className="text-xs text-red-400">{errorMessage(error)}</p>;

  // Group atoms by (role, scope label) — a role attached on X and granted on Y
  // are different facts and must not merge.
  const groups = new Map<string, PermissionSource[]>();
  for (const atom of data.atoms) {
    const scope =
      atom.scope === "global" ? "instance-wide" : (atom.scope_label ?? atom.scope);
    const key = `${atom.role_name ?? "?"} · ${scope}`;
    const list = groups.get(key) ?? [];
    list.push(atom);
    groups.set(key, list);
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
        What membership confers
      </p>
      {groups.size === 0 ? (
        <p className="text-xs text-fg-muted">
          Nothing — this team is not attached to any project and holds no role grants.
        </p>
      ) : (
        [...groups.entries()].map(([label, atoms]) => (
          <div key={label} className="flex flex-wrap items-baseline gap-1.5">
            <span className="shrink-0 text-[11px] font-medium text-fg-secondary">{label}</span>
            {atoms.map((atom) => (
              <span
                key={atom.permission}
                className={
                  "rounded border px-1 font-mono text-[10px] " +
                  (atom.implied ? "border-subtle text-fg-muted" : "border-strong text-fg-secondary")
                }
              >
                {atom.permission}
              </span>
            ))}
          </div>
        ))
      )}
      <ResourceSections sections={data.resources} subject="this team" />
    </div>
  );
}
