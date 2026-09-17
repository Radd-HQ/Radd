import type { ResourceGrantScope } from "./AccessGrantsEditor";
import type { FieldScopePermission } from "../../lib/queries/field-settings";
import { FieldProjectChoices } from "./FieldProjectScope";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { OptionResource, type DirectoryOption } from "../../lib/queries/options";
import { GrantSubject, Permission, type AccessGrantCreate, type GrantSubjectValue } from "../../lib/types";
import { Button } from "../Button";
import { Choices } from "../DirectoryChoices";
import { ErrorText } from "../ErrorText";
import { IconButton } from "../IconButton";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { ProjectPicker } from "../projects/ProjectPicker";
import { GroupReachHint } from "./GroupReachHint";

const subjects = {
  [GrantSubject.user]: { label: "Person", resource: OptionResource.person },
  [GrantSubject.role]: { label: "Role", resource: OptionResource.role },
  [GrantSubject.team]: { label: "Team", resource: OptionResource.teamReference },
  [GrantSubject.group]: { label: "Directory group", resource: OptionResource.group },
};

/** Resource-defined access model with lazy subject/scope selection and one atomic save. */
export function AddResourceGrantDialog({ resourceType, resourceId, accesses, subjectKinds, projectScoped, scope, projectPermission, onClose, onAdded }: {
  resourceType: string; resourceId: string; accesses: string[]; subjectKinds: GrantSubjectValue[];
  projectScoped: boolean; scope?: ResourceGrantScope; projectPermission?: FieldScopePermission; onClose: () => void; onAdded: () => void;
}) {
  const permissions = usePermissions();
  const [kind, setKind] = useState(subjectKinds[0]);
  const [subject, setSubject] = useState<DirectoryOption>();
  const [access, setAccess] = useState(accesses[0]);
  const [effect, setEffect] = useState<"allow" | "deny">("allow");
  const [expiresAt, setExpiresAt] = useState("");
  const [global, setGlobal] = useState(false);
  const scopeChosen = !projectScoped || scope !== undefined || global;
  const [projects, setProjects] = useState<DirectoryOption[]>([]);
  const [picker, setPicker] = useState<"subject" | "project">();
  const canBrowse = kind === GrantSubject.user ||
    (kind === GrantSubject.role && permissions.global(Permission.roleRead)) ||
    (kind === GrantSubject.team && permissions.global(Permission.teamRead)) ||
    (kind === GrantSubject.group && permissions.anyProject(Permission.itemRead));
  const add = useMutation({
    mutationFn: () => api.post(ApiPath.grants, {
      resource_type: resourceType, resource_id: resourceId, subject_type: kind,
      subject_id: subject!.value, access, effect,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
      project_ids: scope !== undefined ? (scope.id === null ? [] : [scope.id]) : projectScoped ? projects.map(p => p.value) : [],
    } satisfies AccessGrantCreate),
    onSuccess: () => { onAdded(); onClose(); },
  });
  return <Modal title="Add resource grant" onClose={onClose}>
    <form className="flex min-w-0 flex-col gap-4" onSubmit={event => {
      event.preventDefault(); if (subject && (scopeChosen || projects.length > 0) && !add.isPending) add.mutate();
    }}>
      <SelectField label="Subject kind" value={kind} onChange={event => {
        setKind(event.target.value as GrantSubjectValue); setSubject(undefined);
      }}>
        {subjectKinds.map(value => <option key={value} value={value}>{subjects[value].label}</option>)}
      </SelectField>
      <Button variant="secondary" aria-label="Choose grant subject" aria-haspopup="dialog"
        disabled={!canBrowse} onClick={() => setPicker("subject")}>
        <span className="truncate">{subject?.label ?? `Choose ${subjects[kind].label.toLowerCase()}…`}</span>
      </Button>
      {!canBrowse && <p className="text-xs text-fg-muted">You need access to this subject directory to choose a subject.</p>}
      {subject?.hint && <p className="text-xs text-fg-muted">{subject.hint}</p>}
      {kind === GrantSubject.group && subject && <GroupReachHint groupId={subject.value} />}
      <SelectField label="Effect" value={effect} onChange={e => setEffect(e.target.value as "allow" | "deny")}>
        <option value="allow">May</option><option value="deny">May not</option>
      </SelectField>
      <SelectField label="Access level" value={access} onChange={e => setAccess(e.target.value)}>
        {accesses.map(value => <option key={value} value={value}>{value}</option>)}
      </SelectField>
      {projectScoped && scope !== undefined && <p className="text-xs text-fg-muted">Grant scope: {scope.label}. This grant applies only in the selected scope.</p>}
      {projectScoped && scope === undefined && <div className="space-y-2">
        <p className="text-xs font-medium text-fg-secondary">Project scope</p>
        {projects.length === 0 ? <p className="text-xs text-fg-muted">Choose projects or explicitly select everywhere.</p> :
          <ul aria-label="Selected grant projects" className="flex max-h-32 flex-wrap gap-1 overflow-auto">
            {projects.map(project => <li key={project.value} className="inline-flex max-w-full items-center gap-1 rounded border border-subtle px-2 py-1 text-xs">
              <span className="truncate">{project.label}</span>
              <IconButton aria-label={`Remove ${project.label}`} onClick={() => setProjects(rows => rows.filter(p => p.value !== project.value))}><X size={12} aria-hidden /></IconButton>
            </li>)}
          </ul>}
        <Button variant="secondary" onClick={() => { setGlobal(false); setPicker("project"); }}>Add projects</Button>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={global} onChange={e => { setGlobal(e.target.checked); setProjects([]); }} />Apply everywhere</label>
      </div>}
      <TextField type="date" label="Expires (optional)" value={expiresAt} onChange={e => setExpiresAt(e.target.value)} hint="Empty means permanent. The grant stops applying at midnight UTC on this date." />
      {add.isError && <div role="alert"><ErrorText error={add.error} /></div>}
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" disabled={!subject || (!scopeChosen && !projects.length) || add.isPending}>{add.isPending ? "Adding…" : "Add grant"}</Button></div>
    </form>
    {picker === "subject" && <Choices resource={subjects[kind].resource} selected={subject?.value} onClose={() => setPicker(undefined)} onSelect={row => { setSubject(row); setPicker(undefined); }} />}
    {picker === "project" && projectPermission && <FieldProjectChoices permission={projectPermission} selected={projects.map(p => p.value)} onClose={() => setPicker(undefined)} onSelect={(id, label) => {
      setProjects(rows => rows.some(p => p.value === id) ? rows : [...rows, { value: id, label, hint: "" }]); setPicker(undefined);
    }} />}
    {picker === "project" && !projectPermission && <ProjectPicker title="Choose grant projects" onClose={() => setPicker(undefined)} onSelect={project => {
      setProjects(rows => rows.some(p => p.value === project.id) ? rows : [...rows, { value: project.id, label: project.key, hint: project.name }]); setPicker(undefined);
    }} />}
  </Modal>;
}
