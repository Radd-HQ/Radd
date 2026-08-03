import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Globe, Plus, ShieldCheck, Users, X } from "lucide-react";
import { projectsQuery, rolesQuery, teamsQuery } from "../../../lib/queries";
import { BASELINE_ROLE_KEY, type Project, type SsoDefaultGrant } from "../../../lib/types";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { ScopePicker } from "../ScopePicker";

/**
 * What a NEW account gets from this provider (RADD-780/781).
 *
 * The same interaction as granting a role on the Users and Teams panels — a
 * list of "Role · Global" / "Role · KEY" rows with a remove ×, and an Add
 * button opening the role picker plus the `ScopePicker`. RADD-777 shipped a
 * single `<select>` for one global role, which could express "everyone gets
 * Member everywhere" and nothing else; a grant is (role, scope), and dropping
 * the scope made the setting unable to say the thing it exists for.
 *
 * The one difference from `RoleGrantsSection`: that one writes immediately
 * against an existing subject, and a provider being CREATED has no id yet. So
 * this is local state saved with the rest of the form.
 */
export function StartingAccess({
  grants,
  onGrantsChange,
  teamIds,
  onTeamIdsChange,
}: {
  grants: SsoDefaultGrant[];
  onGrantsChange: (next: SsoDefaultGrant[]) => void;
  teamIds: string[];
  onTeamIdsChange: (next: string[]) => void;
}) {
  const roles = useQuery(rolesQuery());
  const projects = useQuery(projectsQuery());
  const teams = useQuery(teamsQuery());
  const [adding, setAdding] = useState<"role" | "team" | null>(null);

  const roleName = new Map((roles.data ?? []).map((r) => [r.id, r.name]));
  const projectKey = new Map((projects.data ?? []).map((p) => [p.id, p.key]));
  const teamName = new Map((teams.data ?? []).map((t) => [t.id, t.name]));

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-xs font-medium text-fg-secondary">Roles</p>
          <Button variant="ghost" size="sm" onClick={() => setAdding("role")}>
            <Plus size={12} aria-hidden />
            Add role
          </Button>
        </div>
        {grants.length === 0 ? (
          <p className="text-[11px] text-fg-muted">
            No roles — new accounts start on the Baseline alone.
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {grants.map((grant, index) => (
              <li
                key={`${grant.role_id}:${grant.project_id ?? "global"}`}
                className="flex items-center gap-2 text-[13px]"
              >
                <ShieldCheck size={12} className="text-fg-faint" aria-hidden />
                <span className="text-fg">{roleName.get(grant.role_id) ?? "role"}</span>
                {grant.project_id ? (
                  <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg">
                    {projectKey.get(grant.project_id) ?? "?"}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded border border-emerald-500/30 px-1.5 py-px text-[11px] text-emerald-300">
                    <Globe size={10} aria-hidden /> Global
                  </span>
                )}
                <button
                  type="button"
                  aria-label="Remove role"
                  onClick={() => onGrantsChange(grants.filter((_, i) => i !== index))}
                  className="ml-auto rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
                >
                  <X size={13} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-xs font-medium text-fg-secondary">Teams</p>
          <Button variant="ghost" size="sm" onClick={() => setAdding("team")}>
            <Plus size={12} aria-hidden />
            Add team
          </Button>
        </div>
        {teamIds.length === 0 ? (
          <p className="text-[11px] text-fg-muted">No teams.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {teamIds.map((id) => (
              <li key={id} className="flex items-center gap-2 text-[13px]">
                <Users size={12} className="text-fg-faint" aria-hidden />
                <span className="text-fg">{teamName.get(id) ?? "team"}</span>
                <button
                  type="button"
                  aria-label="Remove team"
                  onClick={() => onTeamIdsChange(teamIds.filter((entry) => entry !== id))}
                  className="ml-auto rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
                >
                  <X size={13} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-[11px] text-fg-faint">
        Applied once, when this provider CREATES an account — never re-applied. Revoke or change
        any of it later and no future sign-in will put it back, which is the difference between a
        starting point and a policy the provider keeps enforcing.
      </p>

      {adding === "role" && (
        <AddRoleDialog
          roles={(roles.data ?? []).filter((role) => role.key !== BASELINE_ROLE_KEY)}
          projects={projects.data ?? []}
          onClose={() => setAdding(null)}
          onAdd={(roleId, projectIds) => {
            // A scope picker with no projects means GLOBAL — one row with a null
            // project, exactly as POST /role-grants treats an empty list.
            const additions: SsoDefaultGrant[] =
              projectIds.length === 0
                ? [{ role_id: roleId, project_id: null }]
                : projectIds.map((projectId) => ({ role_id: roleId, project_id: projectId }));
            const key = (g: SsoDefaultGrant) => `${g.role_id}:${g.project_id ?? "global"}`;
            const seen = new Set(grants.map(key));
            onGrantsChange([...grants, ...additions.filter((g) => !seen.has(key(g)))]);
            setAdding(null);
          }}
        />
      )}
      {adding === "team" && (
        <AddTeamDialog
          // Directory-linked teams are excluded: their membership belongs to the
          // AD group (spec 87), so a template pointing at one could only ever be
          // skipped at login. Offering it would be offering a no-op.
          teams={(teams.data ?? []).filter(
            (team) => team.source !== "directory" && !teamIds.includes(team.id),
          )}
          onClose={() => setAdding(null)}
          onAdd={(teamId) => {
            onTeamIdsChange([...teamIds, teamId]);
            setAdding(null);
          }}
        />
      )}
    </div>
  );
}

function AddRoleDialog({
  roles,
  projects,
  onClose,
  onAdd,
}: {
  roles: { id: string; name: string }[];
  projects: Project[];
  onClose: () => void;
  onAdd: (roleId: string, projectIds: string[]) => void;
}) {
  const [roleId, setRoleId] = useState("");
  const [projectIds, setProjectIds] = useState<string[]>([]);

  return (
    <Modal title="Add a starting role" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <SelectField label="Role" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
          <option value="">Choose a role…</option>
          {roles.map((role) => (
            <option key={role.id} value={role.id}>
              {role.name}
            </option>
          ))}
        </SelectField>
        <div>
          <p className="mb-1.5 text-xs font-medium text-fg-secondary">Scope</p>
          <ScopePicker value={projectIds} onChange={setProjectIds} projects={projects} />
          <p className="mt-1.5 text-[11px] text-fg-faint">
            Global grants the role everywhere; scope it to projects to grant it only there.
          </p>
        </div>
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!roleId} onClick={() => onAdd(roleId, projectIds)}>
            Add
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function AddTeamDialog({
  teams,
  onClose,
  onAdd,
}: {
  teams: { id: string; name: string }[];
  onClose: () => void;
  onAdd: (teamId: string) => void;
}) {
  const [teamId, setTeamId] = useState("");

  return (
    <Modal title="Add a starting team" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <SelectField label="Team" value={teamId} onChange={(e) => setTeamId(e.target.value)}>
          <option value="">Choose a team…</option>
          {teams.map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </SelectField>
        <p className="text-[11px] text-fg-faint">
          Directory-linked teams aren't listed — their membership comes from the AD group, so
          adding someone here would be refused at sign-in.
        </p>
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!teamId} onClick={() => onAdd(teamId)}>
            Add
          </Button>
        </div>
      </div>
    </Modal>
  );
}
