import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { type GrantSubject, grantSubjectParams } from "../../lib/queries/roles";
import { type DirectoryOption, OptionResource } from "../../lib/queries/options";
import { queryKeys } from "../../lib/queries";
import { Button } from "../Button";
import { Choices } from "../DirectoryChoices";
import { ErrorText } from "../ErrorText";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { ProjectPicker } from "../projects/ProjectPicker";

function Preset({ roleKey, label, onSelect }: {
  roleKey: string; label: string; onSelect: (role: DirectoryOption) => void;
}) {
  const role = useQuery({
    queryKey: [...queryKeys.roles, "preset", roleKey],
    queryFn: ({ signal }) => api.get<DirectoryOption[]>("/roles/options", {
      signal, query: { key: roleKey, limit: "1" },
    }),
  });
  return <div>
    <Button variant="ghost" disabled={!role.data?.[0]} onClick={() => onSelect(role.data![0])}>{label}</Button>
    {role.isError && <Button variant="ghost" onClick={() => void role.refetch()}>Retry {label}</Button>}
  </div>;
}

function ScopeChoices({ label, rows, onRemove, onBrowse }: {
  label: string; rows: DirectoryOption[]; onRemove: (id: string) => void; onBrowse: () => void;
}) {
  return <div className="min-w-0 space-y-2">
    <p className="text-xs font-medium text-fg-secondary">{label}</p>
    {rows.length > 0 && <ul aria-label={`Selected ${label.toLowerCase()}`} className="flex max-h-32 flex-wrap gap-1 overflow-auto">
      {rows.map(row => <li key={row.value} className="flex min-w-0 max-w-full items-center gap-1 rounded border border-subtle px-2 py-1 text-xs">
        <span className="truncate" title={row.label}>{row.label}</span>
        <button type="button" className="shrink-0 rounded p-1 text-fg-muted hover:bg-elevated" aria-label={`Remove ${row.label}`} onClick={() => onRemove(row.value)}><X size={12} aria-hidden /></button>
      </li>)}
    </ul>}
    <Button variant="secondary" onClick={onBrowse}>Add {label.toLowerCase()}</Button>
  </div>;
}

/** One role with any combination of project/space scopes; empty means global. */
export function GrantRoleDialog({ subject, onClose, onGranted }: {
  subject: GrantSubject; onClose: () => void; onGranted: () => void;
}) {
  const [global, setGlobal] = useState(false);
  const [expiresAt, setExpiresAt] = useState("");
  const [role, setRole] = useState<DirectoryOption>();
  const [projects, setProjects] = useState<DirectoryOption[]>([]);
  const [spaces, setSpaces] = useState<DirectoryOption[]>([]);
  const [picker, setPicker] = useState<"role" | "project" | "space">();
  const grant = useMutation({
    mutationFn: () => api.post(ApiPath.roleGrants, {
      ...grantSubjectParams(subject), role_id: role!.value,
      project_ids: global ? [] : projects.map(row => row.value), space_ids: global ? [] : spaces.map(row => row.value),
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
    }),
    onSuccess: () => { onGranted(); onClose(); },
  });
  const subjectLabel = "teamId" in subject ? "this team" : "userId" in subject ? "this person" : "this group";
  const hasScope = global || projects.length > 0 || spaces.length > 0;
  return <Modal title="Grant role" onClose={onClose}>
    <form className="flex flex-col gap-4" onSubmit={event => { event.preventDefault(); if (role && hasScope && !grant.isPending) grant.mutate(); }}>
      <div className="flex flex-wrap gap-1">
        <Preset roleKey="viewer" label="Viewer" onSelect={setRole} />
        <Preset roleKey="member" label="Member" onSelect={setRole} />
        <Preset roleKey="admin" label="Admin" onSelect={setRole} />
      </div>
      <div className="min-w-0 space-y-1">
        <p className="text-xs font-medium text-fg-secondary">Role</p>
        <Button variant="secondary" aria-label="Choose role" aria-haspopup="dialog" onClick={() => setPicker("role")}>
          <span className="truncate">{role?.label ?? "Choose a role…"}</span>
        </Button>
      </div>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={global} onChange={e => { setGlobal(e.target.checked); setProjects([]); setSpaces([]); }} />Grant everywhere on this server</label>
      {!global && <><ScopeChoices label="Projects" rows={projects} onBrowse={() => setPicker("project")} onRemove={id => setProjects(rows => rows.filter(row => row.value !== id))} />
      <ScopeChoices label="Wiki spaces" rows={spaces} onBrowse={() => setPicker("space")} onRemove={id => setSpaces(rows => rows.filter(row => row.value !== id))} />
      </>}
      {!hasScope && <p className="text-xs text-fg-muted">Choose a project or wiki space, or explicitly select everywhere.</p>}
      <TextField type="datetime-local" label="Expires (optional)" value={expiresAt} onChange={e => setExpiresAt(e.target.value)} hint="Uses your local time. Empty means permanent." />
      {role && <p className="break-words rounded border border-subtle bg-elevated px-3 py-2 text-xs">
        <strong>{role.label}</strong> granted to {subjectLabel}
        {projects.length > 0 && <> on {projects.map(row => row.label).join(", ")}</>}
        {spaces.length > 0 && <> in {spaces.map(row => row.label).join(", ")}</>}
        {global && <strong className="text-status-warning-ink"> EVERYWHERE on this server</strong>}.
      </p>}
      {grant.isError && <ErrorText error={grant.error} />}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={!role || !hasScope || grant.isPending}>{grant.isPending ? "Granting…" : "Grant"}</Button>
      </div>
    </form>
    {picker === "role" && <Choices resource={OptionResource.role} selected={role?.value} onClose={() => setPicker(undefined)} onSelect={row => { setRole(row); setPicker(undefined); }} />}
    {picker === "project" && <ProjectPicker title="Choose projects" onClose={() => setPicker(undefined)} onSelect={project => {
      setProjects(rows => rows.some(row => row.value === project.id) ? rows : [...rows, { value: project.id, label: project.key, hint: project.name }]);
      setPicker(undefined);
    }} />}
    {picker === "space" && <Choices resource={OptionResource.space} onClose={() => setPicker(undefined)} onSelect={space => {
      setSpaces(rows => rows.some(row => row.value === space.value) ? rows : [...rows, space]); setPicker(undefined);
    }} />}
  </Modal>;
}
