import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { Permission, type RoleGrantCreate } from "../../lib/types";
import { OptionResource, type DirectoryOption } from "../../lib/queries/options";
import { Button } from "../Button";
import { Choices } from "../DirectoryChoices";
import { ErrorText } from "../ErrorText";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { Select } from "../Select";

const subjectResources = { person: OptionResource.person, team: OptionResource.teamReference, group: OptionResource.group };
type SubjectKind = keyof typeof subjectResources;

/** Pick a subject and a role lazily; the destination stays the requested project or wiki space. */
export function GrantScopedRoleDialog({ scopeId, scopeName, kind: scopeKind, onClose, onGranted }: {
  scopeId: string; scopeName: string; kind: "space" | "project"; onClose: () => void; onGranted: () => void;
}) {
  const perms = usePermissions();
  const [expiresAt, setExpiresAt] = useState("");
  const [kind, setKind] = useState<SubjectKind>("person");
  const [subject, setSubject] = useState<DirectoryOption>();
  const [role, setRole] = useState<DirectoryOption>();
  const [picker, setPicker] = useState<"subject" | "role">();
  const canReadRoles = perms.global(Permission.roleRead);
  const grant = useMutation({
    mutationFn: () => api.post(ApiPath.roleGrants, {
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
      role_id: role!.value, ...(scopeKind === "space" ? { space_ids: [scopeId] } : { project_ids: [scopeId] }),
      ...(kind === "team" ? { team_id: subject!.value } : kind === "group" ? { group_id: subject!.value } : { user_id: subject!.value }),
    } satisfies RoleGrantCreate),
    onSuccess: () => { onGranted(); onClose(); },
  });
  return <Modal title={`Grant access to ${scopeName}`} onClose={onClose}>
    <form className="flex min-w-0 flex-col gap-4" onSubmit={event => { event.preventDefault(); if (role && subject && !grant.isPending) grant.mutate(); }}>
      <div className="space-y-2">
        <p className="text-xs font-medium text-fg-secondary">Who</p>
        <Select aria-label="Grant subject kind" value={kind} onChange={value => { setKind(value as SubjectKind); setSubject(undefined); }} options={[
          { value: "person", label: "Person" },
          ...(perms.global(Permission.teamRead) ? [{ value: "team", label: "Team" }] : []),
          ...(perms.anyProject(Permission.itemRead) ? [{ value: "group", label: "Directory group" }] : []),
        ]} />
        <Button variant="secondary" aria-label="Choose grant subject" aria-haspopup="dialog" className="max-w-full" onClick={() => setPicker("subject")}>
          <span className="truncate">{subject?.label ?? `Choose ${kind}…`}</span>
        </Button>
        {subject?.hint && <p className="break-words text-xs text-fg-muted">{subject.hint}</p>}
      </div>
      <div className="space-y-2">
        <p className="text-xs font-medium text-fg-secondary">Role</p>
        <Button variant="secondary" disabled={!canReadRoles} aria-label="Choose grant role" aria-haspopup="dialog" className="max-w-full" onClick={() => setPicker("role")}>
          <span className="truncate">{role?.label ?? "Choose role…"}</span>
        </Button>
        {!canReadRoles && <p className="text-xs text-fg-muted">You need access to the role directory to choose a role.</p>}
      </div>
      <p className="text-xs text-fg-muted">This role applies in {scopeName} only.</p>
      <TextField type="datetime-local" label="Expires (optional)" value={expiresAt} onChange={e => setExpiresAt(e.target.value)} hint="Uses your local time. Empty means permanent." />
      {grant.isError && <div role="alert"><ErrorText error={grant.error} /></div>}
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" disabled={!role || !subject || grant.isPending}>{grant.isPending ? "Granting…" : "Grant"}</Button></div>
    </form>
    {picker === "subject" && <Choices resource={subjectResources[kind]} selected={subject?.value} onSelect={value => { setSubject(value); setPicker(undefined); }} onClose={() => setPicker(undefined)} />}
    {picker === "role" && <Choices resource={OptionResource.assignableRole} scope={scopeKind === "project" ? { project_id: scopeId } : { space_id: scopeId }} selected={role?.value} onSelect={value => { setRole(value); setPicker(undefined); }} onClose={() => setPicker(undefined)} />}
  </Modal>;
}
