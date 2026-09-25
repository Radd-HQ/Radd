import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { Button, Modal, ListSearchInput, DirectoryPager, QueryError, Spinner, usePagedDirectory } from "@radd/plugin-sdk";
import { projectSummaryQuery, projectsPageQuery } from "./directory-queries";
import type { ProjectPickerProps } from "./picker-contract";

/** Project selection queries the whole visible directory in bounded windows. */
export function ProjectPicker({ title, permission = "", onSelect, onClose, selectedId, emptyLabel, onClear }: ProjectPickerProps) {
  const summaryDef = projectSummaryQuery();
  const session = useId();
  const summary = useQuery({ ...summaryDef, queryKey: [...summaryDef.queryKey, session], gcTime: 0, staleTime: 0, retry: false });
  const directory = usePagedDirectory(permission, (q, page) => projectsPageQuery(q, page, false, permission));
  return <Modal title={title} onClose={onClose}>
    <ListSearchInput value={directory.filter} onChange={directory.setFilter}
      placeholder="Search projects by name or key…" total={summary.data?.total ?? directory.total} matched={directory.total} noun="projects" />
    {emptyLabel && onClear && <Button variant="ghost" className="mt-2" onClick={onClear}>{emptyLabel}</Button>}
    <div aria-busy={directory.busy} className="mt-3 max-h-[45dvh] overflow-y-auto">
      {directory.isError ? <div className="space-y-2"><QueryError label="projects" error={directory.error} />
        <Button variant="secondary" onClick={() => void directory.refetch()}>Retry projects</Button></div>
        : directory.isPending ? <Spinner />
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
