import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Trash2, X } from "lucide-react";
import type { SsoDefaultGrant, SsoProvisioningRule } from "../../../lib/types";
import { useKeyedRows } from "../../../lib/keyed-rows";
import { provisioningReferencesQuery } from "../../../lib/queries/provisioning";
import { OptionResource } from "../../../lib/queries/options";
import { Button } from "../../Button";
import { Choices } from "../../DirectoryChoices";
import { DirectoryPager } from "../../DirectoryPager";
import { ErrorText } from "../../ErrorText";
import { IconButton } from "../../IconButton";
import { TokenMultiSelect } from "../../TokenMultiSelect";
import { StartingRoleDialog } from "./StartingRoleDialog";

function useWindow<T>(all: T[], pageSize: number) {
  const [page, setPage] = useState(0);
  useEffect(() => { if (page > 0 && page * pageSize >= all.length) setPage(Math.max(0, Math.ceil(all.length / pageSize) - 1)); }, [page, pageSize, all.length]);
  return { page, setPage, pageSize, total: all.length, busy: false, start: page * pageSize, rows: all.slice(page * pageSize, (page + 1) * pageSize) };
}

/** Local drafts save with the provider; every matching rule applies only at account creation. */
export function StartingAccess({ rules, onChange }: { rules: SsoProvisioningRule[]; onChange: (next: SsoProvisioningRule[]) => void }) {
  const keyed = useKeyedRows(rules, onChange);
  const window = useWindow(rules, 10);
  return <section aria-label="Starting access" className="space-y-3">
    {rules.length === 0 && <p className="text-xs text-fg-muted">No rules — new accounts start on the Baseline alone.</p>}
    {window.rows.map((rule, i) => { const index = window.start + i; return <RuleCard key={keyed.keys[index]} rule={rule}
      onChange={next => onChange(rules.map((r, j) => j === index ? { ...r, ...next } : r))} onRemove={() => keyed.removeAt(index)} />; })}
    <DirectoryPager {...window} onPage={window.setPage} label="starting rules" />
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="min-w-0 flex-1 text-xs text-fg-muted">Every matching domain rule applies once when this provider creates an account. No domains means everyone.</p>
      <Button variant="ghost" size="sm" onClick={() => { keyed.add({ name: "", domains: [], grants: [], team_ids: [] }); window.setPage(Math.floor(rules.length / 10)); }}>Add rule</Button></div>
  </section>;
}

function RuleCard({ rule, onChange, onRemove }: { rule: SsoProvisioningRule; onChange: (next: Partial<SsoProvisioningRule>) => void; onRemove: () => void }) {
  const grants = useWindow(rule.grants, 50);
  const teams = useWindow(rule.team_ids, 50);
  const refs = useQuery(provisioningReferencesQuery(grants.rows.map(r => r.role_id), grants.rows.flatMap(r => r.project_id ? [r.project_id] : []), teams.rows));
  const [adding, setAdding] = useState<"role" | "team">();
  const label = (kind: "roles" | "projects" | "teams", id: string) => refs.data?.[kind][id] ?? (refs.isPending ? "Loading…" : `Unavailable ${kind === "roles" ? "role" : kind === "teams" ? "team" : "project"}`);
  return <div data-starting-rule className="min-w-0 space-y-3 rounded-md border border-subtle bg-base p-3">
    <div className="flex items-center gap-2"><input value={rule.name} onChange={e => onChange({ name: e.target.value })} placeholder="Rule name (optional)" aria-label="Rule name" className="min-w-0 flex-1 rounded border border-subtle bg-transparent px-2 py-1 text-sm text-heading" /><IconButton danger aria-label="Remove rule" onClick={onRemove}><Trash2 size={13} aria-hidden /></IconButton></div>
    <div><p className="mb-1 text-xs text-fg-secondary">Email domains</p><TokenMultiSelect value={rule.domains} onChange={domains => onChange({ domains })} options={[]} allowCreate placeholder="acme.example — empty matches everyone" ariaLabel="Rule email domains" /></div>
    {refs.isError && <div role="alert" className="space-y-1"><ErrorText error={refs.error} /><Button variant="secondary" onClick={() => void refs.refetch()}>Retry access names</Button></div>}
    <div><p className="mb-1 text-xs text-fg-secondary">Roles</p>
      {rule.grants.length === 0 ? <p className="text-xs text-fg-muted">None</p> : <ul aria-label="Starting role grants" className="space-y-1">{grants.rows.map((grant, i) => <li key={`${grant.role_id}:${grant.project_id ?? "global"}:${i}`} className="flex min-w-0 items-center gap-2 text-xs">
        <span className="min-w-0 flex-1 break-words">{label("roles", grant.role_id)} · {grant.project_id ? label("projects", grant.project_id) : "Global"}</span>
        <IconButton aria-label="Remove role" onClick={() => onChange({ grants: rule.grants.filter((_, j) => j !== grants.start + i) })}><X size={12} aria-hidden /></IconButton>
      </li>)}</ul>}
      <DirectoryPager {...grants} onPage={grants.setPage} label="starting grants" /><Button variant="ghost" size="sm" onClick={() => setAdding("role")}>Add role</Button>
    </div>
    <div><p className="mb-1 text-xs text-fg-secondary">Teams</p>
      {rule.team_ids.length === 0 ? <p className="text-xs text-fg-muted">None</p> : <ul aria-label="Starting teams" className="space-y-1">{teams.rows.map(id => <li key={id} className="flex min-w-0 items-center gap-2 text-xs"><span className="min-w-0 flex-1 break-words">{label("teams", id)}</span><IconButton aria-label="Remove team" onClick={() => onChange({ team_ids: rule.team_ids.filter(t => t !== id) })}><X size={12} aria-hidden /></IconButton></li>)}</ul>}
      <DirectoryPager {...teams} onPage={teams.setPage} label="starting teams" /><Button variant="ghost" size="sm" onClick={() => setAdding("team")}>Add team</Button>
    </div>
    {adding === "role" && <StartingRoleDialog onClose={() => setAdding(undefined)} onAdd={(roleId, projectIds) => {
      const additions: SsoDefaultGrant[] = projectIds.length ? projectIds.map(project_id => ({ role_id: roleId, project_id })) : [{ role_id: roleId, project_id: null }];
      const key = (g: SsoDefaultGrant) => `${g.role_id}:${g.project_id ?? "global"}`;
      const seen = new Set(rule.grants.map(key));const next = [...rule.grants, ...additions.filter(g => !seen.has(key(g)))];onChange({ grants: next });grants.setPage(Math.floor(Math.max(0, next.length - 1) / 50));setAdding(undefined);
    }} />}
    {adding === "team" && <Choices resource={OptionResource.teamReference} selectedValues={rule.team_ids} onClose={() => setAdding(undefined)} onSelect={row => { if (!rule.team_ids.includes(row.value)) { onChange({ team_ids: [...rule.team_ids, row.value] }); teams.setPage(Math.floor(rule.team_ids.length / 50)); } setAdding(undefined); }} />}
  </div>;
}
