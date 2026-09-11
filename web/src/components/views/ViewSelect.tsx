import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { viewQuery } from "../../lib/queries/shared-directories";
import { useViewDirectory } from "../../lib/useSharedDirectory";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { ListSearchInput } from "../ListSearchInput";
import { DirectoryPager } from "../DirectoryPager";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { ViewRowContent } from "../shell/SidebarRows";

export function ViewSelect({ value, onChange, label = "Saved view" }: {
  value: string; onChange: (id: string) => void; label?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const selected = useQuery(viewQuery(value));
  return <div className="flex min-w-0 flex-col gap-1.5">
    <label htmlFor={id} className="text-xs font-medium text-fg-secondary">{label}</label>
    <Button id={id} variant="secondary" aria-haspopup="dialog" className="w-full justify-between" onClick={() => setOpen(true)}>
      <span className="truncate">{value ? selected.data?.name ?? (selected.isError ? "Unavailable view" : "Loading view…") : "Choose a view…"}</span>
      <ChevronDown size={12} aria-hidden />
    </Button>
    {open && <ViewChoices onClose={() => setOpen(false)} onSelect={next => { onChange(next); setOpen(false); }} />}
  </div>;
}

function ViewChoices({ onClose, onSelect }: { onClose: () => void; onSelect: (id: string) => void }) {
  const directory = useViewDirectory();
  return <Modal title="Choose a saved view" onClose={onClose}>
    <ListSearchInput value={directory.filter} onChange={directory.setFilter} placeholder="Search saved views…"
      total={directory.total} matched={directory.total} noun="views" />
    <div className="mt-2 max-h-[45dvh] overflow-y-auto" aria-busy={directory.busy}>
      {directory.isError ? <QueryError label="views" error={directory.error} />
        : directory.isPending ? <Spinner label="Loading views…" />
        : <ul>{directory.rows.map(view => <li key={view.id}><Button variant="ghost" className="w-full justify-start"
          onClick={() => onSelect(view.id)}><ViewRowContent view={view} /></Button></li>)}</ul>}
      {!directory.busy && !directory.isError && !directory.rows.length && <p className="py-4 text-sm text-fg-muted">No matching views.</p>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="saved views" />
  </Modal>;
}
