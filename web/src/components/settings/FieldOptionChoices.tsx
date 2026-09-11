import { useEffect, useState } from "react";
import { fieldOptionsQuery, FIELD_DIRECTORY_PAGE_SIZE } from "../../lib/queries/field-settings";
import { useDirectory } from "../../lib/useDirectory";
import { Button } from "../Button";
import { DirectoryPager } from "../DirectoryPager";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { TextField } from "../TextField";

export function FieldOptionChoices({ fieldId, exclude, selected = [], onSelect, onClose }: {
  fieldId: string; exclude?: string; selected?: string[];
  onSelect: (value: string) => void; onClose: () => void;
}) {
  const directory = useDirectory(JSON.stringify([fieldId, exclude]), FIELD_DIRECTORY_PAGE_SIZE,
    (q, page) => fieldOptionsQuery(fieldId, q, page, exclude));
  return <Modal title="Choose field option" onClose={onClose}>
    <TextField type="search" label="Find field option" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} />
    <div aria-busy={directory.busy} className="mt-3 max-h-[45dvh] overflow-y-auto">
      {directory.isPending ? <Spinner label="Loading options…" /> : directory.isError ? <div>
        <QueryError label="field options" error={directory.error} /><Button variant="secondary" onClick={() => void directory.refetch()}>Retry choices</Button>
      </div> : !directory.rows.length ? <p className="text-sm text-fg-muted">No matching options.</p>
        : <ul aria-label="Field option choices">{directory.rows.map(value => <li key={value}>
          <Button variant="ghost" className="h-auto min-h-9 w-full justify-start text-left" disabled={selected.includes(value)} onClick={() => onSelect(value)}>
            <span className="min-w-0 break-words [overflow-wrap:anywhere]">{value || "(empty value)"}</span>
          </Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="field option choices" />
  </Modal>;
}

/** Keep the complete saved draft, while mounting at most one window of values. */
export function FieldDefaultSelection({ fieldId, value, multiple, onChange }: {
  fieldId: string; value: string[]; multiple: boolean; onChange: (value: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const pageSize = FIELD_DIRECTORY_PAGE_SIZE;
  useEffect(() => {
    if (page > 0 && page * pageSize >= value.length) setPage(Math.max(0, Math.ceil(value.length / pageSize) - 1));
  }, [page, value.length]);
  return <div className="space-y-2">
    <p className="text-xs text-fg-secondary">Default value{multiple && value.length > 0 ? ` · ${value.length} selected` : ""}</p>
    {value.length > 0 ? <ul aria-label="Selected default options" className="flex max-h-40 flex-wrap gap-1 overflow-y-auto">
      {value.slice(page * pageSize, (page + 1) * pageSize).map(option => <li key={option} className="flex min-w-0 items-center gap-1 rounded border border-subtle pl-2 text-xs">
        <span className="min-w-0 break-words [overflow-wrap:anywhere]">{option || "(empty value)"}</span>
        <Button size="sm" variant="ghost" aria-label={`Remove default ${option}`} onClick={() => onChange(value.filter(current => current !== option))}>×</Button>
      </li>)}
    </ul> : <p className="text-xs text-fg-muted">No default selected.</p>}
    <DirectoryPager page={page} pageSize={pageSize} total={value.length} busy={false} onPage={setPage} label="selected default options" />
    <Button size="sm" variant="secondary" aria-haspopup="dialog" onClick={() => setOpen(true)}>{multiple ? "Add default option" : "Choose default option"}</Button>
    {open && <FieldOptionChoices fieldId={fieldId} selected={value} onClose={() => setOpen(false)} onSelect={option => {
      onChange(multiple ? [...new Set([...value, option])] : [option]); setOpen(false);
    }} />}
  </div>;
}
