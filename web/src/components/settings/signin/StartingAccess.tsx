import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Globe, Plus, ShieldCheck, Trash2, Users, X } from "lucide-react";
import { projectsQuery, rolesQuery, teamsQuery } from "../../../lib/queries";
import {
  BASELINE_ROLE_KEY,
  type Project,
  type SsoDefaultGrant,
  type SsoProvisioningRule,
} from "../../../lib/types";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { TokenMultiSelect } from "../../TokenMultiSelect";
import { ScopePicker } from "../ScopePicker";
import { useKeyedRows } from "../../../lib/keyed-rows";
import { IconButton } from "../../IconButton";

/**
 * What a NEW account gets from this provider, per rule (RADD-782).
 *
 * One provider serves several populations: `@acme.example` and `@partner.example`
 * arrive through the same Google button and should not land with the same
 * access. So the starting access is a list of RULES, each matching on the email
 * domain and carrying its own roles and teams.
 *
 * **Every matching rule applies** — the copy says so, because it is the one
 * thing an admin can get wrong here. Grants are additive rows, so a union is
 * the only composition that cannot surprise; first-match-wins would let a
 * catch-all at the top silently disable everything below it.
 *
 * Local state saved with the provider, not written immediately like
 * `RoleGrantsSection` — a provider being CREATED has no id to hang rules off.
 */
export function StartingAccess({
  rules,
  onChange,
}: {
  rules: SsoProvisioningRule[];
  onChange: (next: SsoProvisioningRule[]) => void;
}) {
  const roles = useQuery(rolesQuery());
  const projects = useQuery(projectsQuery());
  const teams = useQuery(teamsQuery());

  // Stable per-row keys (RADD-901): rule cards are full of editors, and keying
  // by index re-keyed every card below a removal.
  const rows = useKeyedRows(rules, onChange);
  const patch = (index: number, next: Partial<SsoProvisioningRule>) =>
    onChange(rules.map((rule, i) => (i === index ? { ...rule, ...next } : rule)));

  return (
    <div className="flex flex-col gap-3">
      {rules.length === 0 && (
        <p className="text-[11px] text-fg-muted">
          No rules — new accounts start on the Baseline alone.
        </p>
      )}

      {rules.map((rule, index) => (
        <RuleCard
          key={rows.keys[index]}
          rule={rule}
          roles={(roles.data ?? []).filter((role) => role.key !== BASELINE_ROLE_KEY)}
          projects={projects.data ?? []}
          teams={teams.data ?? []}
          onChange={(next) => patch(index, next)}
          onRemove={() => rows.removeAt(index)}
        />
      ))}

      <div className="flex items-center justify-between">
        <p className="text-[11px] text-fg-faint">
          Every rule whose domains match is applied — a rule with no domains matches everyone.
          Applied once, when this provider CREATES an account, and never re-applied.
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => rows.add({ name: "", domains: [], grants: [], team_ids: [] })}
        >
          <Plus size={12} aria-hidden />
          Add rule
        </Button>
      </div>
    </div>
  );
}

function RuleCard({
  rule,
  roles,
  projects,
  teams,
  onChange,
  onRemove,
}: {
  rule: SsoProvisioningRule;
  roles: { id: string; name: string; key: string }[];
  projects: Project[];
  teams: { id: string; name: string; source?: string }[];
  onChange: (next: Partial<SsoProvisioningRule>) => void;
  onRemove: () => void;
}) {
  const [adding, setAdding] = useState<"role" | "team" | null>(null);
  const roleName = new Map(roles.map((r) => [r.id, r.name]));
  const projectKey = new Map(projects.map((p) => [p.id, p.key]));
  const teamName = new Map(teams.map((t) => [t.id, t.name]));

  return (
    <div className="flex flex-col gap-2 rounded-md border border-subtle bg-base p-3">
      <div className="flex items-center gap-2">
        <input
          value={rule.name}
          onChange={(event) => onChange({ name: event.target.value })}
          placeholder="Rule name (optional)"
          aria-label="Rule name"
          className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-[13px] text-heading hover:border-subtle focus:border-strong focus:outline-none"
        />
        <IconButton
          danger
          onClick={onRemove}
          aria-label="Remove rule"
        >
          <Trash2 size={13} aria-hidden />
        </IconButton>
      </div>

      <div>
        <div className="mb-1 text-[11px] font-medium text-fg-secondary">Email domains</div>
        <TokenMultiSelect
          value={rule.domains}
          onChange={(domains) => onChange({ domains })}
          options={[]}
          allowCreate
          placeholder="acme.example — leave empty to match everyone"
          createLabel={(term) => `Match ${term.replace(/^@/, "")}`}
          ariaLabel="Rule email domains"
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-medium text-fg-secondary">Roles</span>
        {rule.grants.length === 0 && <span className="text-[11px] text-fg-muted">none</span>}
        {rule.grants.map((grant, i) => (
          <span
            key={`${grant.role_id}:${grant.project_id ?? "global"}`}
            className="inline-flex items-center gap-1 rounded border border-strong px-1.5 py-px text-[11px] text-fg"
          >
            <ShieldCheck size={10} aria-hidden className="text-fg-faint" />
            {roleName.get(grant.role_id) ?? "role"}
            {grant.project_id ? (
              <span className="font-mono text-fg-secondary">
                {projectKey.get(grant.project_id) ?? "?"}
              </span>
            ) : (
              <Globe size={10} aria-hidden className="text-emerald-300" />
            )}
            <button
              type="button"
              aria-label="Remove role"
              onClick={() => onChange({ grants: rule.grants.filter((_, j) => j !== i) })}
              className="cursor-pointer text-fg-faint hover:text-red-400"
            >
              <X size={10} aria-hidden />
            </button>
          </span>
        ))}
        <Button variant="ghost" size="sm" onClick={() => setAdding("role")}>
          <Plus size={11} aria-hidden />
          Add role
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-medium text-fg-secondary">Teams</span>
        {rule.team_ids.length === 0 && <span className="text-[11px] text-fg-muted">none</span>}
        {rule.team_ids.map((id) => (
          <span
            key={id}
            className="inline-flex items-center gap-1 rounded border border-strong px-1.5 py-px text-[11px] text-fg"
          >
            <Users size={10} aria-hidden className="text-fg-faint" />
            {teamName.get(id) ?? "team"}
            <button
              type="button"
              aria-label="Remove team"
              onClick={() => onChange({ team_ids: rule.team_ids.filter((t) => t !== id) })}
              className="cursor-pointer text-fg-faint hover:text-red-400"
            >
              <X size={10} aria-hidden />
            </button>
          </span>
        ))}
        <Button variant="ghost" size="sm" onClick={() => setAdding("team")}>
          <Plus size={11} aria-hidden />
          Add team
        </Button>
      </div>

      {adding === "role" && (
        <AddRoleDialog
          roles={roles}
          projects={projects}
          onClose={() => setAdding(null)}
          onAdd={(roleId, projectIds) => {
            // No projects picked means GLOBAL — one row with a null project,
            // exactly as POST /role-grants treats an empty list.
            const additions: SsoDefaultGrant[] =
              projectIds.length === 0
                ? [{ role_id: roleId, project_id: null }]
                : projectIds.map((projectId) => ({ role_id: roleId, project_id: projectId }));
            const key = (g: SsoDefaultGrant) => `${g.role_id}:${g.project_id ?? "global"}`;
            const seen = new Set(rule.grants.map(key));
            onChange({ grants: [...rule.grants, ...additions.filter((g) => !seen.has(key(g)))] });
            setAdding(null);
          }}
        />
      )}
      {adding === "team" && (
        <AddTeamDialog
          // Directory-linked teams are excluded: their membership belongs to the
          // AD group (spec 87), so a rule naming one could only ever be skipped
          // at login. Offering it would be offering a no-op.
          teams={teams.filter((t) => t.source !== "directory" && !rule.team_ids.includes(t.id))}
          onClose={() => setAdding(null)}
          onAdd={(teamId) => {
            onChange({ team_ids: [...rule.team_ids, teamId] });
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
