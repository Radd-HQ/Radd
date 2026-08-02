import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { FolderKanban, Plus } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { projectsQuery } from "../lib/queries";
import { Permission } from "../lib/types";
import { Button } from "../components/Button";
import { Spinner } from "../components/Spinner";
import { NewProjectModal } from "../components/projects/NewProjectModal";
import { QueryError } from "../components/QueryError";

export function ProjectsIndexPage() {
  // Global-scope project.create gates the affordance (spec 06 permission union).
  const canCreate = usePermissions().global(Permission.projectCreate);
  const projects = useQuery(projectsQuery());
  const [creating, setCreating] = useState(false);

  if (projects.isPending) {
    return <Spinner label="Loading projects…" />;
  }

  if (projects.isError) {
    return (
      <div className="p-10">
        <QueryError label="projects" error={projects.error} />
      </div>
    );
  }

  const list = projects.data ?? [];

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

      {list.length === 0 ? (
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
                <span className="ml-auto text-xs text-fg-faint">
                  {new Date(project.created_at).toLocaleDateString()}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {creating && <NewProjectModal onClose={() => setCreating(false)} />}
    </div>
  );
}
