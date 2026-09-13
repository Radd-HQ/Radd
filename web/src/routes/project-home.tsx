import { Navigate, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { RoutePath } from "../lib/constants";
import { useProjectByKey, useAnonymousBounce } from "../lib/hooks";
import { viewsPageQuery } from "../lib/queries";
import { ViewType } from "../lib/types";
import { Spinner } from "../components/Spinner";
import { QueryError } from "../components/QueryError";

/**
 * /p/$projectKey — the project landing. Projects have no special surfaces
 * anymore, only views (seeded with Board/List/Planning at creation), so this
 * simply opens the project's first visible view (server order: position →
 * name). No views left = an empty-state hint; nothing is resolved or stored.
 */
export function ProjectHomePage() {
  const { projectKey = "" } = useParams({ strict: false });
  const { project } = useProjectByKey(projectKey);
  const views = useQuery({ ...viewsPageQuery({ projectId: project?.id, includeGlobal: false, excludeType: ViewType.queue }, "", 0, 1), enabled: Boolean(project) });

  if (project === undefined || (Boolean(project) && views.isPending)) {
    return <Spinner label="Loading project…" />;
  }
  if (project === null) {
    return <ProjectNotFound projectKey={projectKey} />;
  }
  if (views.isError) return <div className="p-10"><QueryError label="views" error={views.error} /></div>;
  const first = views.data?.rows[0];
  if (first) {
    return (
      <Navigate
        to={RoutePath.projectView}
        params={{ projectKey, viewId: first.id }}
        replace
      />
    );
  }
  return (
    <div className="p-10 text-sm text-fg-muted">
      {project.name} has no views yet — create one from the sidebar (+ New view).
    </div>
  );
}


/** Spec 121: a visitor is sent to sign in instead of a dead end. */
function ProjectNotFound({ projectKey }: { projectKey: string }) {
  useAnonymousBounce(true);
  return <div className="p-10 text-sm text-fg-muted">Project “{projectKey}” not found.</div>;
}
