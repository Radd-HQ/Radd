import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { fieldProjectChoicesQuery, fieldProjectReferencesQuery, FIELD_DIRECTORY_PAGE_SIZE, type FieldScopePermission } from "../../lib/queries/field-settings";
import { useDirectory } from "../../lib/useDirectory";
import { Button } from "../Button";
import { IconButton } from "../IconButton";
import { Modal } from "../Modal";
import { ListSearchInput } from "../ListSearchInput";
import { DirectoryPager } from "../DirectoryPager";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";

/** Scope drafts stay complete while selected labels and choices use bounded windows. */
export function FieldProjectScope({ value, onChange, permission, allowGlobal, disabled = false }: {
  value: string[]; onChange: (ids: string[]) => void; permission: FieldScopePermission; allowGlobal: boolean; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const pageSize = FIELD_DIRECTORY_PAGE_SIZE;
  const ids = value.slice(page * pageSize, (page + 1) * pageSize);
  const references = useQuery(fieldProjectReferencesQuery(ids));
  useEffect(() => { if (page > 0 && page * pageSize >= value.length) setPage(Math.max(0, Math.ceil(value.length / pageSize) - 1)); }, [page, value.length]);
  const names = new Map(references.data?.map(row => [row.value, row.label]));
  return <div className="min-w-0 space-y-2">
    {value.length === 0 ? <p className="text-xs text-fg-muted">{allowGlobal ? "Global — available on every project" : "Choose at least one project."}</p> : <>
      <p className="text-xs text-fg-muted">{value.length} selected project{value.length === 1 ? "" : "s"}</p>
      <ul aria-label="Selected field projects" className="flex max-h-40 flex-wrap gap-1 overflow-y-auto">{ids.map(id => <li key={id} className="flex min-w-0 items-center gap-1 rounded border border-subtle px-2 text-xs">
        <span className="truncate">{names.get(id) ?? (references.isPending ? "Loading project…" : "Unavailable project")}</span>
        {!disabled && <IconButton aria-label={`Remove project ${names.get(id) ?? "from scope"}`} disabled={!allowGlobal && value.length === 1} className="flex size-8 shrink-0 items-center justify-center" onClick={() => onChange(value.filter(current => current !== id))}><X size={12} aria-hidden /></IconButton>}
      </li>)}</ul>
      <DirectoryPager page={page} pageSize={pageSize} total={value.length} busy={false} onPage={setPage} label="selected field projects" />
      {references.isError && <div><QueryError label="project names" error={references.error} /><Button variant="ghost" onClick={() => void references.refetch()}>Retry project names</Button></div>}
    </>}
    {!disabled && <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}><Plus size={12} aria-hidden />Add project</Button>
      {allowGlobal && value.length > 0 && <Button size="sm" variant="ghost" onClick={() => onChange([])}>Make global</Button>}
    </div>}
    {!allowGlobal && value.length > 0 && !disabled && <p className="text-xs text-fg-faint">At least one project is required. Global availability needs global field permissions.</p>}
    {open && <FieldProjectChoices permission={permission} selected={value} onClose={() => setOpen(false)} onSelect={id => { onChange([...new Set([...value, id])]); setOpen(false); }} />}
  </div>;
}

export function FieldProjectChoices({ permission, selected, onSelect, onClose }: { permission: FieldScopePermission; selected: string[]; onSelect: (id: string, label: string) => void; onClose: () => void }) {
  const directory = useDirectory(permission, FIELD_DIRECTORY_PAGE_SIZE, (q, page) => fieldProjectChoicesQuery(permission, q, page));
  return <Modal title="Choose field project" onClose={onClose}>
    <ListSearchInput value={directory.filter} onChange={directory.setFilter} placeholder="Search projects by key or name…" matched={directory.total} noun="projects" />
    <div aria-busy={directory.busy} className="mt-3 max-h-[45dvh] overflow-y-auto">
      {directory.isPending ? <Spinner label="Loading projects…" /> : directory.isError ? <div><QueryError label="field projects" error={directory.error} /><Button variant="secondary" onClick={() => void directory.refetch()}>Retry field projects</Button></div>
        : directory.rows.length === 0 ? <p className="text-sm text-fg-muted">No matching projects you can use for this field.</p>
        : <ul>{directory.rows.map(row => <li key={row.value}><Button variant="ghost" disabled={selected.includes(row.value)} className="w-full justify-start" onClick={() => onSelect(row.value, row.label)}><span className="shrink-0 font-mono">{row.label}</span><span className="truncate">{row.hint}</span></Button></li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="field project choices" />
  </Modal>;
}
