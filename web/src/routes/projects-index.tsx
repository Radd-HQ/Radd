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
import { api, formatDate, relativeTime } from "@radd/plugin-sdk";
import { useQuery } from "@tanstack/react-query";

/** What the row says about a project's work (RADD-1558), keyed by project id. */
type ProjectStats = Record<string, { open_items: number; last_activity_at: string | null }>;

export function ProjectsIndexPage() {
  // Global-scope project.create gates the affordance (spec 06 permission union).
  const canCreate = usePermissions().global(Permission.projectCreate);
  const projects = useProjectDirectory();
  const [creating, setCreating] = useState(false);
  const list = projects.rows;
  // Open issues and last activity for the rows on this page: asked for here,
  // by the page that shows them, not carried on the sidebar's project list.
  const ids = list.map((project) => project.id);
  const stats = useQuery({
    queryKey: ["projectStats", ids],
    queryFn: ({ signal }) =>
      api.get<ProjectStats>(`/items/project-stats?${ids.map((id) => `project_id=${id}`).join("&")}`, { signal }),
    enabled: ids.length > 0,
    staleTime: 60_000,
  });

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
                    <span className="flex min-w-0 flex-col">
                      <span className="text-sm text-heading">{project.name}</span>
                      {project.description && (
                        <span className="truncate text-xs text-fg-muted">{project.description}</span>
                      )}
                    </span>
                    {project.public && <PublicProjectChip />}
                    <ProjectRowStats
                      stats={stats.data?.[project.id]}
                      createdAt={project.created_at}
                    />
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

/** Right-hand side of a project row: how much is open, and when it last moved.
 *  A project nobody has touched says when it was created instead, labelled. */
function ProjectRowStats({
  stats,
  createdAt,
}: {
  stats: ProjectStats[string] | undefined;
  createdAt: string;
}) {
  return (
    <span className="ml-auto flex shrink-0 items-baseline gap-4 text-xs text-fg-muted" data-project-stats>
      {stats && (
        <span className="tabular-nums">
          <span className="font-medium text-fg">{stats.open_items.toLocaleString()}</span> open
        </span>
      )}
      <span className="w-36 text-right text-fg-faint">
        {stats?.last_activity_at
          ? `Active ${relativeTime(stats.last_activity_at)}`
          : `Created ${formatDate(createdAt)}`}
      </span>
    </span>
  );
}
