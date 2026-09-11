import { Modal } from "../Modal";
import { Button } from "../Button";
import { ListSearchInput } from "../ListSearchInput";
import { DirectoryPager } from "../DirectoryPager";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { Check } from "lucide-react";
import { useProjectDirectory } from "../../lib/useProjectDirectory";
import type { PermissionValue, Project } from "../../lib/types";

/** Project selection queries the whole visible directory in bounded windows. */
export function ProjectPicker({ title, permission = "", onSelect, onClose, selectedId, emptyLabel, onClear }: {
  title: string; permission?: PermissionValue; onSelect: (project: Project) => void; onClose: () => void;
  selectedId?: string; emptyLabel?: string; onClear?: () => void;
}) {
  const directory = useProjectDirectory(false, permission);
  return <Modal title={title} onClose={onClose}>
    <ListSearchInput value={directory.filter} onChange={directory.setFilter}
      placeholder="Search projects by name or key…" total={directory.available} matched={directory.total} noun="projects" />
    {emptyLabel && onClear && <Button variant="ghost" className="mt-2" onClick={onClear}>{emptyLabel}</Button>}
    <div aria-busy={directory.busy} className="mt-3 max-h-[45dvh] overflow-y-auto">
      {directory.isError ? <div className="space-y-2"><QueryError label="projects" error={directory.error} />
        <Button variant="secondary" onClick={() => void directory.refetch()}>Retry projects</Button></div>
        : directory.isPending ? <Spinner label="Loading projects…" />
        : directory.rows.length === 0 ? <p className="py-4 text-sm text-fg-muted">No matching projects.</p>
        : <ul>{directory.rows.map(project => <li key={project.id}>
          <Button variant="ghost" className="w-full justify-start" onClick={() => onSelect(project)}>
            <span className="shrink-0 font-mono">{project.key}</span><span className="truncate">{project.name}</span>
            {project.id === selectedId && <Check size={12} className="ml-auto shrink-0" aria-label="Selected" />}
          </Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="project choices" />
  </Modal>;
}
