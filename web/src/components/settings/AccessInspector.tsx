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
import { Users, UsersRound } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import {
  teamAccessQuery,
  userAccessQuery,
  userPermissionsQuery,
} from "../../lib/queries";
import { GrantSubject, type Membership, type PermissionSource, type ResourceTypeAccess } from "../../lib/types";
import { SelectField } from "../SelectField";
import { ProjectSelect } from "../projects/ProjectSelect";
import { OptionSelect } from "../DirectoryChoices";
import { OptionResource } from "../../lib/queries/options";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";

/** The atom half resolves only an explicitly selected scope; catalogs open lazily. */
export function EffectivePermissions({ userId }: { userId: string }) {
  return <section aria-label="Effective permissions"><PermissionExplanation key={userId} userId={userId} /></section>;
}

function PermissionExplanation({ userId }: { userId: string }) {
  const [kind, setKind] = useState("global");
  const [target, setTarget] = useState("");
  const ready = kind === "global" || Boolean(target);
  const { data, isPending, isError, error, refetch } = useQuery({
    ...userPermissionsQuery(userId, { projectId: kind === "project" ? target : undefined,
      spaceId: kind === "space" ? target : undefined }), enabled: ready,
  });
  const picker = <div className="flex flex-wrap items-end gap-2">
    <div className="min-w-0 flex-1">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">Effective permissions</p>
      <SelectField label="Resolution scope" value={kind} onChange={event => { setKind(event.target.value); setTarget(""); }}>
        <option value="global">Instance-wide</option><option value="project">On a project</option><option value="space">In a wiki space</option>
      </SelectField>
    </div>
    {kind === "project" && <div className="min-w-0 basis-60 grow"><ProjectSelect label="Permission project" value={target} onChange={setTarget} /></div>}
    {kind === "space" && <div className="min-w-0 basis-60 grow"><OptionSelect label="Permission wiki space" resource={OptionResource.space} value={target} onChange={setTarget} /></div>}
  </div>;
  if (!ready) return <div className="space-y-2">{picker}<p className="text-xs text-fg-muted">Choose a {kind === "project" ? "project" : "wiki space"} to resolve permissions.</p></div>;

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
        <div role="alert"><ErrorText error={error} /></div>
        <Button variant="secondary" onClick={() => void refetch()}>Retry permissions</Button>
      </div>
    );

  const rows = data ?? [];
  const admin = rows.find((row) => row.kind === "instance-admin");
  if (admin) {
    return (
      <div className="space-y-2">{picker}<p className="rounded-md border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-fg-secondary">
        <strong className="text-heading">Everything.</strong> An instance administrator bypasses
        every permission check, so no role or grant applies — switch Administrator off to make
        the rules below take effect.
      </p></div>
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

/** RADD-820: when a grant ends — amber inside a week (the timesheet's
 * out-of-range treatment), quiet otherwise. */
export function ExpiryChip({ expiresAt }: { expiresAt: string }) {
  const ends = new Date(expiresAt);
  const soon = ends.getTime() - Date.now() < 7 * 24 * 3600 * 1000;
  return (
    <span
      className={
        "ml-1 rounded border px-1 text-[10px] " +
        (soon ? "border-amber-500/40 text-amber-400" : "border-subtle text-fg-faint")
      }
      title={`Expires ${ends.toLocaleString()}`}
    >
      expires {ends.toLocaleDateString()}
    </span>
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
      {first?.via === "group" && first.via_group ? (
        <span className="text-fg-faint">
          {" "}
          granted to group {first.group_path?.length ? first.group_path.join(" ← ") : first.via_group}
        </span>
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
          : atom.via === "group"
            ? atom.group_path?.length
              ? `Granted to the ${atom.via_group ?? "?"} group — you are a member ${atom.group_path.length - 1} level(s) down: ${atom.group_path.join(" ← ")}.`
              : `Granted to the ${atom.via_group ?? "?"} group (you are a direct member).`
            : "";
  return via ? `${base} ${via}` : base;
}

/** The spec-92 half: resource grants reaching this person, plus the counts. */
export function ResourceAccessSection({ userId }: { userId: string }) {
  const { data, isPending, isError, error } = useQuery(userAccessQuery(userId));
  if (isPending) return <p className="text-xs text-fg-muted">Resolving resource access…</p>;
  if (isError) return <ErrorText error={error} />;
  const summary = data.summary;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
        Resource access
      </p>
      {/* RADD-933: full reach and own-items-only reach are DIFFERENT answers.
          Counted together, an account holding nothing but the Baseline's
          `item.read@own` reported "can read items in 97 of 97 projects", which
          reads as "sees everything" and is why a correctly-revoked account
          looked like it was still leaking. */}
      <p className="text-xs text-fg-secondary">
        Can read <strong>every item</strong> in {summary.readable_projects} and edit in{" "}
        {summary.updatable_projects} of {summary.total_projects} projects
        {summary.readable_spaces != null && summary.total_spaces != null ? (
          <>
            {" "}
            · can read <strong>{summary.readable_spaces}</strong> of {summary.total_spaces} wiki
            spaces
          </>
        ) : null}
        .
      </p>
      {(summary.own_readable_projects > 0 || summary.own_updatable_projects > 0) && (
        <p className="text-xs text-fg-muted">
          Beyond that, only <strong>their own</strong> (or participating) items: readable in{" "}
          {summary.own_readable_projects}, editable in {summary.own_updatable_projects} further
          projects. That is real access to real rows — it is simply not the same as reading the
          project.
        </p>
      )}
      <MembershipsSection memberships={data.memberships ?? []} />
      <ResourceSections sections={data.resources} subject="they" />
    </div>
  );
}

/**
 * The carriers between "granted to" and "held by" (RADD-933).
 *
 * The Users page could list a person's DIRECT grants and the atoms they end up
 * with, and nothing in between — so "which teams is this person on, and what do
 * they confer?" had no answer on the page that answers every other access
 * question. A carrier that confers nothing is still listed, and says so: it is
 * exactly the row that will explain the change when someone later grants a role
 * to that team.
 */
function MembershipsSection({ memberships }: { memberships: Membership[] }) {
  if (memberships.length === 0) {
    return (
      <p className="text-xs text-fg-muted">On no teams or directory groups.</p>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
        Teams and groups
      </p>
      <ul className="flex flex-col gap-1">
        {memberships.map((entry) => {
          const Icon = entry.kind === GrantSubject.group ? UsersRound : Users;
          return (
            <li key={`${entry.kind}:${entry.id}`} className="flex flex-wrap items-center gap-1.5 text-xs">
              <Icon size={12} className="shrink-0 text-fg-faint" aria-hidden />
              <span className="text-fg">{entry.name}</span>
              {entry.path && entry.path.length > 1 && (
                <span
                  className="text-[11px] text-fg-faint"
                  title={`Nesting chain, granted group first: ${entry.path.join(" ← ")}`}
                >
                  ({entry.path.length - 1} level{entry.path.length > 2 ? "s" : ""} down)
                </span>
              )}
              {entry.confers.length === 0 ? (
                <span className="text-[11px] text-fg-faint">grants nothing</span>
              ) : (
                entry.confers.map((grant, index) => (
                  <span
                    key={`${grant.role_name}-${grant.scope_label ?? "global"}-${index}`}
                    className="rounded border border-strong px-1.5 py-px text-[11px] text-fg-secondary"
                  >
                    {grant.role_name}
                    <span className="text-fg-faint">
                      {" · "}
                      {grant.scope_label ?? "everywhere"}
                    </span>
                  </span>
                ))
              )}
            </li>
          );
        })}
      </ul>
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
                    {row.granted_by_name ? ` · granted by ${row.granted_by_name}` : ""}
                  </span>
                  {row.expires_at && <ExpiryChip expiresAt={row.expires_at} />}
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
  if (isError) return <ErrorText error={error} />;

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
          This team currently confers no permissions through role grants.
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
