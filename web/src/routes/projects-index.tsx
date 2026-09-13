import { PublicProjectChip } from "../components/items/ItemBadges";
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { FolderKanban, Plus } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { useProjectDirectory } from "../lib/useProjectDirectory";
import { DirectoryPager } from "../components/DirectoryPager";
import { Permission } from "../lib/types";
import { Button } from "../components/Button";
import { ListSearchInput } from "../components/ListSearchInput";
import { Spinner } from "../components/Spinner";
import { NewProjectModal } from "../components/projects/NewProjectModal";
import { QueryError } from "../components/QueryError";
import { formatDate } from "../lib/dates";

export function ProjectsIndexPage() {
  // Global-scope project.create gates the affordance (spec 06 permission union).
  const canCreate = usePermissions().global(Permission.projectCreate);
  const projects = useProjectDirectory();
  const [creating, setCreating] = useState(false);
  const list = projects.rows;

  return (
    <div className="px-8 py-8">
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-heading">Projects</h1>
        {canCreate && (
          <Button onClick={() => setCreating(true)}>
            <Plus size={14} aria-hidden />
            New project
          </Button>
        )}
      </div>

      {!projects.filter && !projects.isPending && !projects.isError && projects.total === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-subtle py-16 text-fg-muted">
          <FolderKanban size={24} aria-hidden />
          <p className="text-sm">No projects yet.</p>
          {canCreate && (
            <Button variant="ghost" onClick={() => setCreating(true)}>
              <Plus size={14} aria-hidden />
              Create the first project
            </Button>
          )}
        </div>
      ) : (
        <>
          <ListSearchInput
              className="mb-3"
              value={projects.filter}
              onChange={projects.setFilter}
              placeholder="Filter projects by name or key…"
              total={projects.available}
              matched={projects.total}
              noun="projects"
          />
          {projects.isError ? <QueryError label="projects" error={projects.error} />
            : projects.isPending ? <Spinner label="Loading projects…" />
            : list.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-subtle py-16 text-fg-muted">
              <FolderKanban size={24} aria-hidden />
              <p className="text-sm">No projects match “{projects.filter.trim()}”.</p>
            </div>
          ) : (
            <ul className="divide-y divide-subtle/80 rounded-lg border border-subtle">
              {list.map((project) => (
                <li key={project.id}>
                  <Link
                    to={RoutePath.project}
                    params={{ projectKey: project.key }}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-surface/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
                  >
                    <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg">
                      {project.key}
                    </span>
                    <span className="text-sm text-heading">{project.name}</span>
                    {project.public && <PublicProjectChip />}
                    <span className="ml-auto text-xs text-fg-faint">
                      {formatDate(project.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <DirectoryPager {...projects} onPage={projects.setPage} label="projects" />
        </>
      )}

      {creating && <NewProjectModal onClose={() => setCreating(false)} />}
    </div>
  );
}
