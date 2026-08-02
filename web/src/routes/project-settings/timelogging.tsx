import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderKanban } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiProjectTimeloggingPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { projectsQuery, projectTimeloggingQuery, queryKeys } from "../../lib/queries";
import { Permission, type Project, type ProjectTimeLogging } from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Per-project time-logging enablement (spec 50). Split out of the global
 * time-logging admin: the shared work categories stay in global settings;
 * the on/off toggle for THIS project lives here. Gated on
 * `project.manage` for the project resolved from the URL context (`projectId`).
 */
export function ProjectTimeloggingSettingsPage({ projectId }: { projectId?: string }) {
  const projects = useQuery(projectsQuery());
  const project = (projects.data ?? []).find((entry) => entry.id === projectId);

  return (
    <SettingsPage
      title="Time logging"
      description="Enable time logging for this project. When on, people can log worklogs and estimates on its issues."
    >
      {projects.isPending ? (
        <TableSkeleton rows={1} />
      ) : !project ? (
        <EmptyState icon={FolderKanban} message="Project not found." />
      ) : (
        <ul className="rounded-lg border border-subtle">
          <ProjectEnableRow project={project} />
        </ul>
      )}
    </SettingsPage>
  );
}

function ProjectEnableRow({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const canManage = perms.project(project, Permission.projectManage);
  const config = useQuery(projectTimeloggingQuery(project.id));
  const enabled = config.data?.enabled ?? false;

  const toggle = useMutation({
    mutationFn: (next: boolean) =>
      api.put<ProjectTimeLogging>(apiProjectTimeloggingPath(project.id), { enabled: next }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.projectTimelogging(project.id) }),
  });

  return (
    <li className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
        {project.key}
      </span>
      <span className="truncate text-[13px] text-fg">{project.name}</span>
      <label className="ml-auto flex items-center gap-2 text-xs text-fg-secondary">
        {toggle.isError && <span className="text-red-400">{errorMessage(toggle.error)}</span>}
        <span>{enabled ? "Enabled" : "Disabled"}</span>
        <input
          type="checkbox"
          checked={enabled}
          disabled={!canManage || config.isPending || toggle.isPending}
          onChange={(event) => toggle.mutate(event.target.checked)}
          aria-label={`Time logging for ${project.key}`}
          className="size-4 cursor-pointer accent-accent disabled:cursor-not-allowed disabled:opacity-50"
        />
      </label>
    </li>
  );
}
