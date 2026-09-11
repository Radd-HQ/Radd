import { useState } from "react";
import type { DirectoryOption } from "../../../lib/queries/options";
import { OptionResource } from "../../../lib/queries/options";
import { IconButton } from "../../IconButton";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { Choices } from "../../DirectoryChoices";
import { ProjectPicker } from "../../projects/ProjectPicker";
import { X } from "lucide-react";

export function StartingRoleDialog({ onClose, onAdd }: { onClose: () => void; onAdd: (roleId: string, projectIds: string[]) => void }) {
  const [role, setRole] = useState<DirectoryOption>();
  const [projects, setProjects] = useState<DirectoryOption[]>([]);
  const [picker, setPicker] = useState<"role" | "project">();
  return <Modal title="Add a starting role" onClose={onClose}>
    <div className="space-y-4">
      <div><p className="mb-1 text-xs text-fg-secondary">Role</p><Button variant="secondary" aria-label="Starting role" aria-haspopup="dialog" onClick={() => setPicker("role")}><span className="truncate">{role?.label ?? "Choose a role…"}</span></Button></div>
      <div className="space-y-2"><p className="text-xs text-fg-secondary">Project scope</p>
        {projects.length === 0 ? <p className="text-xs text-fg-muted">Global — everywhere.</p> : <ul aria-label="Selected starting projects" className="flex max-h-32 flex-wrap gap-1 overflow-auto">{projects.map(p => <li key={p.value} className="inline-flex max-w-full items-center gap-1 rounded border border-subtle px-2 py-1 text-xs"><span className="truncate">{p.label}</span><IconButton aria-label={`Remove ${p.label}`} onClick={() => setProjects(rows => rows.filter(row => row.value !== p.value))}><X size={12} aria-hidden /></IconButton></li>)}</ul>}
        <Button variant="secondary" onClick={() => setPicker("project")}>Add projects</Button>
        <p className="text-xs text-fg-muted">Leave projects empty to grant the role everywhere. Baseline already applies to everyone.</p>
      </div>
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!role} onClick={() => onAdd(role!.value, projects.map(p => p.value))}>Add</Button></div>
    </div>
    {picker === "role" && <Choices resource={OptionResource.assignableRole} selected={role?.value} onSelect={row => { setRole(row); setPicker(undefined); }} onClose={() => setPicker(undefined)} />}
    {picker === "project" && <ProjectPicker title="Choose starting projects" onSelect={project => { setProjects(rows => rows.some(r => r.value === project.id) ? rows : [...rows, { value: project.id, label: project.key, hint: project.name }]); setPicker(undefined); }} onClose={() => setPicker(undefined)} />}
  </Modal>;
}
