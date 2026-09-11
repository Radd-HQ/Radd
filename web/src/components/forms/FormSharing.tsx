import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2, User, Users } from "lucide-react";
import { api } from "../../lib/api";
import { apiFormSharingPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { queryKeys, formSharingQuery, formShareCandidatesQuery, FORM_SHARING_PAGE_SIZE, FormShareKind, type FormShareKindValue } from "../../lib/queries";
import { useDirectory } from "../../lib/useDirectory";
import { Button } from "../Button";
import { useOnLeaveIds } from "../PersonName";
import { DirectoryPager } from "../DirectoryPager";
import { ErrorText } from "../ErrorText";
import { IconButton } from "../IconButton";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { SelectField } from "../SelectField";
import { Spinner } from "../Spinner";
import { TextField } from "../TextField";

/** Individual portal shares save immediately without replacing unseen recipients. */
export function FormSharing({ formId, projectId }: { formId: string; projectId: string }) {
  const queryClient = useQueryClient();
  const onLeaveIds = useOnLeaveIds();
  const [adding, setAdding] = useState(false);
  const directory = useDirectory(`form-shares:${formId}`, FORM_SHARING_PAGE_SIZE, (q, page) => formSharingQuery(formId, q, page));
  useEffect(() => {
    if (directory.isSuccess && !directory.busy && directory.page > 0 && directory.page * directory.pageSize >= directory.total) {
      directory.setPage(Math.max(0, Math.ceil(directory.total / directory.pageSize) - 1));
    }
  }, [directory.isSuccess, directory.busy, directory.page, directory.pageSize, directory.total, directory.setPage]);
  const refresh = async () => {
    await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.forms(projectId) }), invalidateEntities(queryClient, Entity.form)]);
  };
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${apiFormSharingPath(formId)}/${id}`),
    onSuccess: refresh,
  });
  return <section aria-label="Portal sharing" className="flex min-w-0 flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3">
    <p className="text-[13px] text-fg">Portal sharing</p>
    <p className="text-xs text-fg-muted">People and teams listed here see this form on the Portal and can submit it without other permissions. Sharing changes save immediately.</p>
    <TextField type="search" label="Find portal shares" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} />
    {directory.isPending ? <Spinner label="Loading portal shares…" /> : directory.isError ? <div>
      <QueryError label="portal shares" error={directory.error} /><Button variant="ghost" onClick={() => void directory.refetch()}>Retry portal shares</Button>
    </div> : <>
      {!directory.rows.length ? <p className="text-xs text-fg-muted">{directory.filter ? "No matching portal shares." : "No portal shares yet."}</p> :
        <ul aria-label="Portal shares" aria-busy={directory.busy} className="max-h-64 overflow-y-auto">{directory.rows.map(row => <li key={row.id} className="flex min-w-0 items-center gap-2 border-b border-subtle py-2">
          {row.user_id ? <User size={14} aria-label="Person" className="shrink-0" /> : <Users size={14} aria-label="Team" className="shrink-0" />}
          <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere] text-xs">{row.subject_name ?? "Unavailable subject"}{row.user_id && onLeaveIds.has(row.user_id) ? " (away)" : ""}{row.active === false && <span className="text-fg-muted"> (inactive)</span>}</span>
          <IconButton danger aria-label={`Remove portal share ${row.subject_name ?? row.id}`} disabled={remove.isPending} onClick={() => remove.mutate(row.id)}><Trash2 size={13} aria-hidden /></IconButton>
        </li>)}</ul>}
    </>}
    <DirectoryPager {...directory} onPage={directory.setPage} label="portal shares" />
    <Button variant="secondary" className="self-start" onClick={() => setAdding(true)}>Add portal share</Button>
    {remove.isError && <div role="alert"><ErrorText error={remove.error} /></div>}
    {adding && <AddPortalShare formId={formId} onClose={() => setAdding(false)} onAdded={refresh} />}
  </section>;
}

function AddPortalShare({ formId, onClose, onAdded }: { formId: string; onClose: () => void; onAdded: () => Promise<void> }) {
  const [kind, setKind] = useState<FormShareKindValue>(FormShareKind.user);
  const [subject, setSubject] = useState<{ value: string; label: string }>();
  const [choosing, setChoosing] = useState(false);
  const add = useMutation({
    mutationFn: () => api.post(apiFormSharingPath(formId), kind === FormShareKind.user ? { user_id: subject!.value } : { team_id: subject!.value }),
    onSuccess: async () => { await onAdded(); onClose(); },
  });
  return <Modal title="Add portal share" onClose={() => { if (!add.isPending) onClose(); }}>
    <div className="space-y-3">
      <SelectField label="Portal subject kind" value={kind} disabled={add.isPending} onChange={event => { setKind(event.target.value as FormShareKindValue); setSubject(undefined); }}>
        <option value={FormShareKind.user}>Person</option><option value={FormShareKind.team}>Team</option>
      </SelectField>
      <Button variant="secondary" aria-label="Choose portal subject" aria-haspopup="dialog" disabled={add.isPending} onClick={() => setChoosing(true)}><span className="truncate">{subject?.label ?? "Choose a person or team…"}</span></Button>
      {add.isError && <div role="alert"><ErrorText error={add.error} /></div>}
      <div className="flex justify-end gap-2"><Button variant="ghost" disabled={add.isPending} onClick={onClose}>Cancel</Button><Button disabled={!subject || add.isPending} onClick={() => add.mutate()}>{add.isPending ? "Sharing…" : "Share form"}</Button></div>
    </div>
    {choosing && <PortalSubjectChoices formId={formId} kind={kind} onClose={() => setChoosing(false)} onSelect={row => { setSubject(row); setChoosing(false); }} />}
  </Modal>;
}

function PortalSubjectChoices({ formId, kind, onClose, onSelect }: {
  formId: string; kind: FormShareKindValue; onClose: () => void; onSelect: (row: { value: string; label: string }) => void;
}) {
  const onLeaveIds = useOnLeaveIds();
  const directory = useDirectory(`portal-candidates:${formId}:${kind}`, FORM_SHARING_PAGE_SIZE, (q, page) => formShareCandidatesQuery(formId, kind, q, page));
  useEffect(() => {
    if (directory.isSuccess && !directory.busy && directory.page > 0 && directory.page * directory.pageSize >= directory.total) {
      directory.setPage(Math.max(0, Math.ceil(directory.total / directory.pageSize) - 1));
    }
  }, [directory.isSuccess, directory.busy, directory.page, directory.pageSize, directory.total, directory.setPage]);
  return <Modal title="Choose portal recipient" onClose={onClose}>
    <TextField type="search" label="Find portal recipients" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} />
    <div className="mt-2 max-h-[45dvh] overflow-y-auto" aria-busy={directory.busy}>
      {directory.isPending ? <Spinner label="Loading portal recipients…" /> : directory.isError ? <div><QueryError label="portal recipients" error={directory.error} /><Button variant="ghost" onClick={() => void directory.refetch()}>Retry portal recipients</Button></div> :
        !directory.rows.length ? <p className="text-xs text-fg-muted">No matching unshared recipients available.</p> :
        <ul aria-label="Portal recipient choices">{directory.rows.map(row => <li key={row.value}><Button variant="ghost" className="w-full justify-start" onClick={() => onSelect(row)}><span className="truncate">{row.label}{kind === FormShareKind.user && onLeaveIds.has(row.value) ? " (away)" : ""}</span></Button></li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="portal recipients" />
  </Modal>;
}
