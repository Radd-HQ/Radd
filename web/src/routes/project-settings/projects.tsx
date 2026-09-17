import { useQuery } from "@tanstack/react-query";
import { projectByIdQuery } from "../../lib/queries";
import { usePermissions } from "../../lib/hooks";
import { Permission } from "../../lib/types";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopedAccessPanel } from "../../components/settings/ScopedAccessPanel";
import { PublicAccessCard } from "../../components/settings/PublicAccessCard";
import { QueryError } from "../../components/QueryError";
import { TableSkeleton } from "../../components/TableSkeleton";

export function ProjectAccessSettingsPage({ projectId }: { projectId?: string }) {
  const query = useQuery(projectByIdQuery(projectId ?? ""));
  const perms = usePermissions();
  const project = query.data;
  return <SettingsPage history={{ entities: ["project", "role"], projectId }} title="Project access" description="Who can do what here. Each row grants a role to a person, team or directory group; team and group grants include nested members.">
    {projectId && query.isPending ? <TableSkeleton rows={3} /> : query.isError ? <QueryError label="project" error={query.error} />
      : !project ? <p className="text-sm text-fg-muted">Project not found.</p>
      : <div className="flex flex-col gap-4">
          <PublicAccessCard project={project} canManage={perms.project(project, Permission.projectManage)} />
          <ScopedAccessPanel key={project.id} kind="project" scopeId={project.id} scopeName={project.name}
            canGrant={perms.global(Permission.roleUpdate) || perms.project(project, Permission.memberCreate)}
            canRenew={perms.global(Permission.roleUpdate) || perms.project(project, Permission.memberUpdate)}
            canRevoke={perms.global(Permission.roleUpdate) || perms.project(project, Permission.memberDelete)} />
        </div>}
  </SettingsPage>;
}
